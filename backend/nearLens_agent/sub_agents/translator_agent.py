from google.adk.agents import Agent
from nearLens_agent.tools.instructions import TRANSLATOR_AGENT_INSTRUCTION

translator_agent = Agent(
    name="nearlens_translator_agent",
    model="gemini-2.5-flash",
    description="Handles language translation for NearLens.",
    instruction=TRANSLATOR_AGENT_INSTRUCTION,
)
