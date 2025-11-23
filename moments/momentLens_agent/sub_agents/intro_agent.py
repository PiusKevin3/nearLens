from google.adk.agents import Agent
from momentLens_agent.tools.instructions import MOMENTLENS_INTRO_AGENT_INSTRUCTION


intro_agent = Agent(
    name="momentlens_intro_agent",
    model="gemini-2.5-flash",
    description="Handles initial interaction for MomentLens.",
    instruction=MOMENTLENS_INTRO_AGENT_INSTRUCTION,
)
