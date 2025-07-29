from google.adk.agents import Agent,LlmAgent,SequentialAgent
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools import google_search  # Import the tool
from aavraa_assistant.instructions import (AAVRAA_INTRODUCTORY_AGENT_INSTRUCTION,AAVRAA_SHOP_AGENT_INSTRUCTION,MARKET_RESEARCHER_AGENT_INSTRUCTION)
import os
import requests
import json
from typing import Dict
from pydantic import BaseModel, Field
from typing import List, Optional
from tools.orchestrator_tools import WorkerAgentTool


try:
    from dotenv import load_dotenv
    load_dotenv()
    MODEL_NAME = os.environ.get("GOOGLE_GENAI_MODEL", "gemini-2.0-flash-exp")
except ImportError:
    MODEL_NAME = "gemini-2.0-flash-exp"

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

class ShopResponse(BaseModel):
    speakable_summary: str = Field(description="Friendly summary for the user")
    # raw_result: ShoppingItemsResponse


def call_vector_search(url, query, rows=None):
    """
    Calls the Vector Search backend for querying.

    Args:
        url (str): The URL of the search endpoint.
        query (str): The query string.
        rows (int, optional): The number of result rows to return. Defaults to None.

    Returns:
        dict: The JSON response from the API.
    """

    # Build HTTP headers and a payload
    headers = {'Content-Type': 'application/json'}
    payload = {
        "query": query,
        "rows": rows,
        "dataset_id": "mercari3m_mm", # Use Mercari 3M multimodal index
        "use_dense": True, # Use multimodal search
        "use_sparse": True, # Use keyword search too
        "rrf_alpha": 0.5, # Both results are merged with the same weights
        "use_rerank": True, # Use Ranking API for reranking
    }

    # Send an HTTP request to the search endpoint
    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload))
        response.raise_for_status()  # Raise an exception for bad status codes
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error calling the API: {e}")
        return None

from typing import List, Dict, Any

def find_shopping_items(queries: List[str]) -> Dict[str, Any]:
    """
    Searches an e-commerce vector database for shopping items based on a list of search queries.

    When to use:
        Use this tool when a user has expressed interest in discovering or browsing products,
        and you want to retrieve a list of relevant items from the product database.

    Args:
        queries: A list of user-intent-refined search queries (e.g., "men's blue linen shirt", "wireless earbuds").

    Returns:
        A dictionary with the following structure:
        {
            "status": "success" | "error",
            "items": [  # only if status is "success"
                {
                    "name": str,
                    "description": str,
                    "image_url": str,
                    "price": str ,
                    "id": str (optional)
                },
                ...
            ],
            "error_message": str (optional if status == "error")
        }

    Notes:
        - Returns the top items found across all queries, merged into one list.
        - The "items" field is suitable for rendering directly in the display UI.
        - If no items are found or an error occurs, "items" may be an empty list or omitted.
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

# def find_shopping_items(queries: list[str]) -> Dict[str, str]:
#     """
#     Find shopping items from the e-commerce site with the specified list of
#     queries.

#     Args:
#         queries: the list of queries to run.
#     Returns:
#         A dict with the following one property:
#             - "status": returns the following status:
#                 - "success": successful execution
#             - "items": items found in the e-commerce site.
#     """
#     url = "https://www.ac0.cloudadvocacyorg.joonix.net/api/query"

#     items = []
#     for query in queries:
#         result = call_vector_search(
#             url=url,
#             query=query,
#             rows=3,
#         )
#         items.extend(result["items"])

    
#     return items

# Create agents
# introductory_agent = LlmAgent(
#     name="Aavraa_introductory_agent",
#     model="gemini-2.0-flash-exp",
#     instruction=AAVRAA_INTRODUCTORY_AGENT_INSTRUCTION,
#     description = "I am Aavraa, your intelligent lifestyle guide. I help users shop smarter, move faster, discover nearby trends, and get things done effortlessly using taps or voice commands. Powered by AI, I provide personalized assistance tailored to each user’s needs." ,  # Instructions to set the agent's behavior.
#     output_key="Aavraa_introductory_agent_data"
# )

introductory_agent = LlmAgent(
    name="Aavraa_introductory_agent",
    model="gemini-2.0-flash-exp",
    instruction=('''
        I am Aavraa — a location-based marketplace and intelligent lifestyle super-app built to simplify how you live, shop, and connect.
        Just introduce yourself to the user as aavraa and then recieve the user query and forward it to `aavraa_research_agent_data` of research_agent to work on it.
        Just tell the user something like; let's help you get what you need faster and without a hustle. 
        Please be straight to the point and dont ask the user many questions.
        Please also dont mention any agent name or what your doing next for the user to publicly know

    '''),
    description = "I am Aavraa, your intelligent lifestyle guide. I help users shop smarter, move faster, discover nearby trends, and get things done effortlessly using taps or voice commands. Powered by AI, I provide personalized assistance tailored to each user’s needs." ,  # Instructions to set the agent's behavior.
    output_key="Aavraa_introductory_agent_data"
)

research_agent = LlmAgent(
    model="gemini-2.0-flash-exp",
    name='aavraa_research_agent',
    description=('''
        A market researcher for Aavraa. Receives a search request
        from a user, and returns a list of 5 generated queries in English.
    '''),
    instruction=('''
        Your role is a market researcher for Aavraa a location based market-place,e-commerce site,super-app which helps users discover useful products, businesses, services, and trends around them with millions of
    items.
    When you recieved a search request from a user or if forwared by `Aavraa_introductory_agent_data` of introductory_agent, use Google Search tool to
    research on what kind of items people are purchasing for the user's intent.

    Then, generate 5 queries finding those items on Aavraa and
    return them.    
    
    '''),
    tools=[google_search],
    output_key="aavraa_research_agent_data"
)

shopping_worker_agent = LlmAgent(
    model="gemini-2.0-flash-exp",
    name='shopping_worker_agent',
    description="Finds shopping items using research agent and find_shopping_items tool.",
    instruction="""
    You are a smart shopping assistant. Your primary goal is to help users find products:
    1. Uses the research agent to break down the user query into 5 refined search queries.
    2. When a user asks to find products or browse items, **you MUST use the `find_shopping_items` tool**. After executing the `find_shopping_items` tool, **your final response MUST be JSON object**.
    Do NOT add any conversational text, greetings, or explanations outside of the JSON object. Just output the JSON and then inform the `shop_agent` which is next in line that the search query items are ready for the user to view and shop accordingly.
    3. Respond with only a JSON object matching this schema:
    
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
    output_key="shopping_worker_agent_data"
)

shop_agent = LlmAgent(
    name="shop_agent",
    model="gemini-2.0-flash-exp",
    instruction=('''
        You receieve success or failure response from `shopping_worker_agent_data` and then Summarize using the product name and short description the result items from `shopping_worker_agent_data` to the user and show them briefly why they buying any of them could be of advantage and why they wont regret their purchase
    '''),
    description = "Shop assistant product summarizer" ,
)

# aavraa_orchestrator = shopping_worker_agent

# Create sequential agent pipeline
aavraa_orchestrator = SequentialAgent(
    name="Aavraa",
    sub_agents=[
        introductory_agent,
        shopping_worker_agent,
        # shop_agent        
    ],
    # global_instructions= "Shop assistant product summarizer"
)


# # worker_tool = WorkerAgentTool(app_name="Aavraa", agent=shopping_worker_agent)

# aavraa_orchestrator = LlmAgent(
#     model=MODEL_NAME,
#     name='aavraa_orchestrator',
#     description="Main assistant. Delegates shopping logic and formats results.",
#     instruction="""
# 1. Use the 'get_items_from_worker' tool to query for shopping items.
# 2. You will receive a JSON response with status, items, and error (if any).
# 3. Return:
# {
#   "speakable_summary": "...",  # Friendly message to user
#   "raw_result": {...}          # JSON from worker agent
# }
# """,
#     # tools=[
#     #     # AgentTool(
#     #     #     name="get_items_from_worker",
#     #     #     description="Gets shopping items in structured JSON.",
#     #     #     func=worker_tool,
#     #     # ),
#     #     worker_tool
#     # ],
#     output_schema=ShopResponse  # optional, for enforced schema
# )

# shop_agent = LlmAgent(
#     model=MODEL_NAME,
#     name='aavraa_shop_agent',
#     description="Mother agent that handles shopping queries and summarizes responses.",
#     instruction=f"""
#     You are the mother shopping agent on Aavraa.
#     1. Forward the user's product-related query to the `shopping_worker_agent` using the `call_sub_agent_for_items` tool.
#     2. You will receive a JSON response with shopping items.
#     3. Summarize the response in a natural, friendly tone for the user (especially if spoken aloud).
#     4. Your output should look like this:
#     ```json
#     {{
#     "speakable_summary": "I found 3 items for you including noise-canceling earbuds and a stylish watch. Would you like me to show them?",
#     }}
#     """,
#     output_schema=ShopResponse
# )



# shop_agent = Agent(
#     model="gemini-2.0-flash-exp",
#     name='aavraa_shop_agent',
#     description=(
#         'Your smart shopping companion on Aavraa — helping you discover products, compare prices, and connect with trusted sellers in real time.'
#     ),
#     instruction=AAVRAA_SHOP_AGENT_INSTRUCTION,
#     tools=[
#         AgentTool(agent=introductory_agent),
#         AgentTool(agent=research_agent),
#         find_shopping_items,
#     ],
#     # output_schema=ShoppingItemsResponse,   # ⬅ enforce JSON structure
#     # output_key="found_items", 
    
# )


# Create sequential agent pipeline
# aavraa_orchestrator = SequentialAgent(
#     name="Aavraa",
#     sub_agents=[
#         introductory_agent,
#         shop_agent        
#     ]
# )

# aavraa_orchestrator = shop_agent

# aavraa_orchestrator = Agent(
#    # A unique name for the agent.
#    name="google_search_agent",
#    # The Large Language Model (LLM) that agent will use.
#    model="gemini-2.0-flash-exp", # if this model does not work, try below
#    #model="gemini-2.0-flash-exp",
#    # A short description of the agent's purpose.
#    description="Agent to answer questions using Google Search.",
#    # Instructions to set the agent's behavior.
#    instruction="Answer the question using the Google Search tool.",
#    # Add google_search tool to perform grounding with Google search.
#    tools=[google_search],
# )
