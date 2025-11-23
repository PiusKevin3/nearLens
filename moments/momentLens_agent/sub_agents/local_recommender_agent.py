import json
from google.adk.agents import Agent
from momentLens_agent.tools.places_tool import find_nearby_places
from momentLens_agent.tools.instructions import LOCAL_RECOMMENDER_AGENT_INSTRUCTION

local_recommender_agent = Agent(
    name="momentlens_local_recommender",
    model="gemini-2.5-flash",
    description="Finds nearby services and places based on the received inferred moment insights",
    instruction=LOCAL_RECOMMENDER_AGENT_INSTRUCTION,
    tools=[find_nearby_places],
)
