from google.adk.agents import Agent,SequentialAgent
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools import google_search  # Import the tool
from aavraa_assistant.instructions import (AAVRAA_INTRODUCTORY_AGENT_INSTRUCTION,AAVRAA_SHOP_AGENT_INSTRUCTION,MARKET_RESEARCHER_AGENT_INSTRUCTION)
import os
import requests
import json
from typing import Dict

try:
    from dotenv import load_dotenv
    load_dotenv()
    MODEL_NAME = os.environ.get("GOOGLE_GENAI_MODEL", "gemini-2.0-flash-exp")
except ImportError:
    MODEL_NAME = "gemini-2.0-flash-exp"


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
    
def find_shopping_items(queries: list[str]) -> Dict[str, str]:
    """
    Find shopping items from the e-commerce site with the specified list of
    queries.

    Args:
        queries: the list of queries to run.
    Returns:
        A dict with the following one property:
            - "status": returns the following status:
                - "success": successful execution
            - "items": items found in the e-commerce site.
    """
    url = "https://www.ac0.cloudadvocacyorg.joonix.net/api/query"

    items = []
    for query in queries:
        result = call_vector_search(
            url=url,
            query=query,
            rows=3,
        )
        items.extend(result["items"])

    
    return items

# Create agents
introductory_agent = Agent(
    name="Aavraa_introductory_agent",
    model="gemini-2.0-flash-exp",
    instruction=AAVRAA_INTRODUCTORY_AGENT_INSTRUCTION,
    description = "I am Aavraa, your intelligent lifestyle guide. I help users shop smarter, move faster, discover nearby trends, and get things done effortlessly using taps or voice commands. Powered by AI, I provide personalized assistance tailored to each user’s needs." ,  # Instructions to set the agent's behavior.
)

research_agent = Agent(
    model="gemini-2.0-flash-exp",
    name='aavraa_research_agent',
    description=('''
        A market researcher for Aavraa. Receives a search request
        from a user, and returns a list of 5 generated queries in English.
    '''),
    instruction=MARKET_RESEARCHER_AGENT_INSTRUCTION,
    tools=[google_search],
)

shop_agent = Agent(
    model="gemini-2.0-flash-exp",
    name='aavraa_shop_agent',
    description=(
        'Your smart shopping companion on Aavraa — helping you discover products, compare prices, and connect with trusted sellers in real time.'
    ),
    instruction=AAVRAA_SHOP_AGENT_INSTRUCTION,
    tools=[
        AgentTool(agent=introductory_agent),
        AgentTool(agent=research_agent),
        find_shopping_items,
    ],
    
)


# Create sequential agent pipeline
# aavraa_orchestrator = SequentialAgent(
#     name="Aavraa",
#     sub_agents=[
#         introductory_agent,
#         shop_agent        
#     ]
# )

aavraa_orchestrator = shop_agent

# aavraa_orchestrator = Agent(
#    # A unique name for the agent.
#    name="google_search_agent",
#    # The Large Language Model (LLM) that agent will use.
#    model="gemini-2.0-flash-exp", # if this model does not work, try below
#    #model="gemini-2.0-flash-live-001",
#    # A short description of the agent's purpose.
#    description="Agent to answer questions using Google Search.",
#    # Instructions to set the agent's behavior.
#    instruction="Answer the question using the Google Search tool.",
#    # Add google_search tool to perform grounding with Google search.
#    tools=[google_search],
# )
