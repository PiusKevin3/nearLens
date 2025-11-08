import json
from google.adk.agents import Agent
from nearLens_agent.tools.places_tool import find_nearby_places
from nearLens_agent.tools.instructions import LOCAL_RECOMMENDER_AGENT_INSTRUCTION

local_recommender_agent = Agent(
    name="nearlens_local_recommender",
    model="gemini-2.5-flash",
    description="Finds nearby shops and services based on the image label.",
    instruction=LOCAL_RECOMMENDER_AGENT_INSTRUCTION,
    tools=[find_nearby_places],
)
