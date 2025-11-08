from google.adk.agents import Agent
from nearLens_agent.tools.instructions import NEARLENS_INTRO_AGENT_INSTRUCTION


intro_agent = Agent(
    name="nearlens_intro_agent",
    model="gemini-2.5-flash",
    description="Handles initial interaction for NearLens.",
    instruction=NEARLENS_INTRO_AGENT_INSTRUCTION,
)
