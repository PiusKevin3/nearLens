from google.adk.agents import Agent
from momentLens_agent.tools.instructions import TRANSLATOR_AGENT_INSTRUCTION

translator_agent = Agent(
    name="momentlens_translator_agent",
    model="gemini-2.5-flash",
    description="Handles language translation for MomentLens.",
    instruction=TRANSLATOR_AGENT_INSTRUCTION,
)
