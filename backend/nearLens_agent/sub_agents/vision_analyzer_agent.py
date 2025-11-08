from google.adk.agents import Agent
from nearLens_agent.tools.instructions import VISION_ANALYZER_AGENT_INSTRUCTION


vision_analyzer_agent = Agent(
    name="nearlens_vision_analyzer",
    model="gemini-2.5-flash",
    description="Analyzes uploaded images for key objects or items.",
    instruction=VISION_ANALYZER_AGENT_INSTRUCTION,
    output_key="vision_analyzer_labels",
)
