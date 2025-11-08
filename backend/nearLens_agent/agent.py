
from google.adk.agents import SequentialAgent
from .sub_agents.intro_agent import intro_agent
from .sub_agents.vision_analyzer_agent import vision_analyzer_agent
from .sub_agents.local_recommender_agent import local_recommender_agent
from .sub_agents.translator_agent import translator_agent

nearlens_orchestrator = SequentialAgent(
    name="nearlens_orchestrator",
    description="Coordinates NearLens workflow: intro → vision analysis → recommendations.",
    sub_agents=[
        intro_agent,
        vision_analyzer_agent,
        local_recommender_agent,
    ],
)

root_agent = nearlens_orchestrator
