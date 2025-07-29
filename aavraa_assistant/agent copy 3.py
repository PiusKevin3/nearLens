# aavraa_assistant/agent.py
import os
import requests
import json
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

from google.adk.agents import Agent, LlmAgent, SequentialAgent
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools import google_search
from aavraa_assistant.instructions import (AAVRAA_INTRODUCTORY_AGENT_INSTRUCTION, AAVRAA_SHOP_AGENT_INSTRUCTION, MARKET_RESEARCHER_AGENT_INSTRUCTION)
from tools.orchestrator_tools import WorkerAgentTool # Assuming this exists and is needed

try:
    from dotenv import load_dotenv
    load_dotenv()
    MODEL_NAME = os.environ.get("GOOGLE_GENAI_MODEL", "gemini-2.0-flash-exp")
except ImportError:
    MODEL_NAME = "gemini-2.0-flash-exp"

# --- Pydantic Models (Keep as is) ---
class ShoppingItem(BaseModel):
    name: str = Field(description="The name of the product")
    description: str = Field(description="A short product description")
    image_url: str = Field(description="The full image URL")
    price: str = Field(description="The product's price")
    id: Optional[str] = Field(default=None, description="An optional unique identifier")

class ShoppingItemsResponse(BaseModel):
    status: str = Field(description="Status of execution, either 'success' or 'error'")
    items: Optional[List[ShoppingItem]] = Field(default=None, description="List of matched products")
    error_message: Optional[str] = Field(default=None, description="Error message if any failure occurred")

# --- call_vector_search and find_shopping_items (Keep as is) ---
def call_vector_search(url, query, rows=None):
    """
    Calls the Vector Search backend for querying.
    """
    headers = {'Content-Type': 'application/json'}
    payload = {
        "query": query,
        "rows": rows,
        "dataset_id": "mercari3m_mm",
        "use_dense": True,
        "use_sparse": True,
        "rrf_alpha": 0.5,
        "use_rerank": True,
    }
    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error calling the API: {e}")
        return None

def find_shopping_items(queries: List[str]) -> Dict[str, Any]:
    """
    Searches an e-commerce vector database for shopping items based on a list of search queries.
    """
    url = "https://www.ac0.cloudadvocacyorg.joonix.net/api/query"
    items = []
    try:
        for query in queries:
            result = call_vector_search(
                url=url,
                query=query,
                rows=3,
            )
            if "items" in result:
                items.extend(result["items"])
        return {
            "status": "success",
            "items": items
        }
    except Exception as e:
        return {
            "status": "error",
            "error_message": str(e)
        }

# --- Agent Definitions ---

introductory_agent = LlmAgent(
    name="Aavraa_introductory_agent",
    model=MODEL_NAME, # Use MODEL_NAME constant
    # instruction=AAVRAA_INTRODUCTORY_AGENT_INSTRUCTION,
    instruction="I am Aavraa, your intelligent lifestyle guide. I help users shop smarter, move faster, discover nearby trends, and get things done effortlessly using taps or voice commands. Powered by AI, I provide personalized assistance tailored to each user’s needs. Remeber not to ask the user many questions about what they want get what they want and forward to next agent",

    description="I am Aavraa, your intelligent lifestyle guide. I help users shop smarter, move faster, discover nearby trends, and get things done effortlessly using taps or voice commands. Powered by AI, I provide personalized assistance tailored to each user’s needs.",
    output_key="Aavraa_introductory_agent_data"
)

research_agent = LlmAgent(
    model=MODEL_NAME,
    name='aavraa_research_agent',
    description=('''
        A market researcher for Aavraa. Receives a search request
        from a user, and returns a list of 5 generated queries in English.
    '''),
    instruction=MARKET_RESEARCHER_AGENT_INSTRUCTION,
    tools=[google_search],
    output_key="aavraa_research_agent_data"
)

shopping_worker_agent = LlmAgent(
    model=MODEL_NAME,
    name='shopping_worker_agent',
    description="Finds shopping items using research agent and find_shopping_items tool.",
    instruction="""
    You are a smart shopping assistant. Your primary goal is to help users find products:
    1. Uses the research agent to break down the user query into 5 refined search queries.
    2. When a user asks to find products or browse items, **you MUST use the `find_shopping_items` tool**. After executing the `find_shopping_items` tool, **your final response MUST be a JSON object**.
    Do NOT add any conversational text, greetings, or explanations outside of the JSON object. Just output the JSON.
    3. The JSON object MUST match this schema (including the triple backticks for markdown formatting):

    
    { "status": "success", "items": [
     {
    "name": "Product name",
    "description": "Short description",
    "image_url": "Full image URL",
    "price": "Optional price if available",
    "id": "Optional unique ID"
    },
    {
    "name": "Product name",
    "description": "Short description",
    "image_url": "Full image URL",
    "price": "Optional price if available",
    "id": "Optional unique ID"
    }
    ], "error_message": null }
    
    """,
    output_key="shopping_worker_agent_data",
    # IMPORTANT: Set output_schema to guide the ADK, even if the LLM's raw text includes markdown.
    output_schema=ShoppingItemsResponse
)

shop_agent = LlmAgent(
    name="shop_agent",
    model=MODEL_NAME,
    instruction='''
        You are a shopping summarizer. You receive a structured JSON object containing a list of shopping items
        from the previous agent. Your task is to provide a brief, friendly, and engaging spoken summary for the user
        about the items found. Do not include any JSON or markdown in your response. Just plain, conversational text.

        If there are no items found, you should state that clearly and offer alternatives.

        Example of a good response (for items found):
        "I found a few items for you! There's a classic men's Oxford shirt, a slim-fit option, and a sleek Calvin Klein dress shirt. For women, I found a comfortable Hanes t-shirt and an Amazon Essentials crewneck. Would you like to know more about any specific item or see them on your screen?"

        Example of response (no items found):
        "I couldn't find any items matching your request this time. Perhaps you could try a different search term, or would you like me to look for something else?"

        Example of structured input you might receive:
        
        {
          "status": "success",
          "items": [
            {
              "name": "Amazon Essentials Men's Regular-Fit Long-Sleeve Pocket Oxford Shirt",
              "description": "A classic, versatile white Oxford shirt for men.",
              "image_url": "...",
              "price": "$24.90",
              "id": "B071F9QYTK"
            },
            {
              "name": "Goodthreads Men's Slim-Fit Long-Sleeve Oxford Shirt",
              "description": "A slim-fit, long-sleeve white Oxford shirt for a modern look.",
              "image_url": "...",
              "price": "$32.10",
              "id": "B076DXXL6P"
            }
          ],
          "error_message": null
        }
        
    ''',
    description = "Shop assistant product summarizer" ,
    # IMPORTANT: shop_agent should NOT have an output_schema that forces JSON.
    # Its output is meant to be plain text for speaking.
)

# Create sequential agent pipeline
aavraa_orchestrator = SequentialAgent(
    name="Aavraa",
    sub_agents=[
        introductory_agent,
        shopping_worker_agent,
        shop_agent
    ]
)