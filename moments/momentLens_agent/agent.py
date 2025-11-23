
from google.adk.agents import SequentialAgent
from .sub_agents.intro_agent import intro_agent
from .sub_agents.moment_analyzer_agent import vision_analyzer_agent
from .sub_agents.local_recommender_agent import local_recommender_agent
from .sub_agents.translator_agent import translator_agent

momentlens_orchestrator = SequentialAgent(
    name="momentlens_orchestrator",
    description="Coordinates MomentLens workflow: intro → moment analysis → recommendations.",
    sub_agents=[
        intro_agent,
        vision_analyzer_agent,
        local_recommender_agent,
    ],
)

root_agent = momentlens_orchestrator
