from google.adk.agents import Agent,SequentialAgent
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools import google_search  # Import the tool
from aavraa_assistant.instructions import (AAVRAA_INTRODUCTORY_AGENT_INSTRUCTION,AAVRAA_SHOP_AGENT_INSTRUCTION,MARKET_RESEARCHER_AGENT_INSTRUCTION)
import os
import requests
import json
from typing import Dict
from supabase import create_client, Client
from typing import Dict, List, Any, Optional, TypedDict
from datetime import datetime
# from postgrest.exceptions import APIResponseException # <--- ADD THIS IMPORT

try:
    from dotenv import load_dotenv
    load_dotenv()
    MODEL_NAME = os.environ.get("GOOGLE_GENAI_MODEL", "gemini-2.0-flash-exp")
except ImportError:
    MODEL_NAME = "gemini-2.0-flash-exp"

SUPABASE_URL: str = os.environ.get("SUPABASE_URL")
SUPABASE_KEY: str = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Supabase URL and Key must be set as environment variables.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Define the ProductOrService structure using TypedDict for clarity ---
class CustomerReview(TypedDict):
    id: str
    author: str
    rating: int
    comment: str

class ProductOrService(TypedDict, total=False):
    id: str
    name: str
    description: str
    price: float
    currency: str
    business_name: str
    business_id: str
    category: str

    image_url: Optional[str]
    rating: Optional[float]
    reviews_count: Optional[int]
    is_deal: Optional[bool]
    deal_price: Optional[float]
    discount_percentage: Optional[float]
    expires_at: Optional[datetime]
    location: Optional[str]
    material: Optional[str]
    dimensions: Optional[str]
    color: Optional[str]
    warranty: Optional[str]
    customer_reviews: Optional[List[CustomerReview]]

def find_shopping_items(queries: List[str]) -> Dict[str, Any]:
    """
    Find shopping items from a Supabase products table based on a list of queries,
    returning data conforming to the ProductOrService interface.

    Args:
        queries: The list of queries (search terms) to run.
                 These terms will be used to search against 'name' and 'description' fields.
    Returns:
        A dict with the following properties:
            - "status": "success" if successful, "error" otherwise.
            - "message": (optional) An error message if status is "error".
            - "items": A list of ProductOrService objects found in the Supabase products table.
    """
    all_found_items: List[ProductOrService] = []
    seen_item_ids = set()
    errors = []

    for query_term in queries:
        try:
            # Escape special characters
            safe_term = query_term.replace('%', '\\%').replace('_', '\\_')
            # Example: "men shirts" -> "%men shirts%"
            pattern = f"%{safe_term}%"

            # Build query with OR condition for name and description
            query = supabase.table("products").select("*")
            query = query.or_(f"name.ilike.{pattern},description.ilike.{pattern}")
            response = query.execute()

            # Handle errors
            if response.error:
                errors.append(f"Query '{query_term}' failed: {response.error.message}")
                continue

            # Process data
            if response.data:
                for item_data in response.data:
                    item_id = item_data.get("id")
                    if item_id and item_id not in seen_item_ids:
                        product: ProductOrService = {
                            "id": item_data.get("id"),
                            "name": item_data.get("name"),
                            "description": item_data.get("description"),
                            "price": float(item_data.get("price")) if item_data.get("price") is not None else 0.0,
                            "currency": item_data.get("currency"),
                            "business_name": item_data.get("business_name"),
                            "business_id": item_data.get("business_id"),
                            "category": item_data.get("category"),
                        }

                        # Optional fields
                        if item_data.get("image_url"):
                            product["image_url"] = item_data["image_url"]
                        if item_data.get("rating") is not None:
                            product["rating"] = float(item_data["rating"])
                        if item_data.get("reviews_count") is not None:
                            product["reviews_count"] = int(item_data["reviews_count"])
                        if item_data.get("is_deal") is not None:
                            product["is_deal"] = item_data["is_deal"]
                        if item_data.get("deal_price") is not None:
                            product["deal_price"] = float(item_data["deal_price"])
                        if item_data.get("discount_percentage") is not None:
                            product["discount_percentage"] = float(item_data["discount_percentage"])

                        expires_at_str = item_data.get("expires_at")
                        if expires_at_str:
                            try:
                                product["expires_at"] = datetime.fromisoformat(expires_at_str)
                            except ValueError:
                                print(f"Warning: Could not parse expires_at '{expires_at_str}' for item {item_id}")
                                product["expires_at"] = None

                        for key in ["location", "material", "dimensions", "color", "warranty"]:
                            if item_data.get(key):
                                product[key] = item_data[key]

                        customer_reviews_data = item_data.get("customer_reviews")
                        if customer_reviews_data is not None:
                            if isinstance(customer_reviews_data, list):
                                product["customer_reviews"] = customer_reviews_data
                            else:
                                print(f"Warning: customer_reviews for item {item_id} is not a list.")
                                product["customer_reviews"] = []
                        else:
                            product["customer_reviews"] = []

                        all_found_items.append(product)
                        seen_item_ids.add(item_id)

        except Exception as e:
            errors.append(f"Query '{query_term}' failed: {str(e)}")
            continue

    return {
        "status": "success" if not errors else "partial_success",
        "items": all_found_items,
        "message": " | ".join(errors) if errors else None,
    }


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