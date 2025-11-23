from google.adk.agents import Agent
from momentLens_agent.tools.instructions import MOMENT_ANALYZER_AGENT_INSTRUCTION
from google.adk.tools import google_search


vision_analyzer_agent = Agent(
    name="momentlens_vision_analyzer",
    model="gemini-2.5-flash",
    description="Analyze the current moment based on location, time, weather, and local context, and generate actionable insights.",
    instruction=MOMENT_ANALYZER_AGENT_INSTRUCTION,
    output_key="moment_analyzer_labels",
    tools=[google_search],
)
