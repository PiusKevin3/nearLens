import os
import uuid
import json
import asyncio
from google.adk.agents import LlmAgent, SequentialAgent
from google.adk.tools import google_search
from google.adk.sessions import DatabaseSessionService
from google.adk.runners import Runner
from google.genai import types

try:
    from dotenv import load_dotenv
    load_dotenv()
    MODEL_NAME = os.environ.get("GOOGLE_GENAI_MODEL", "gemini-2.0-flash")
except ImportError:
    MODEL_NAME = "gemini-2.0-flash"

# Import instructions
from aavraa_ai_agent.instructions import (
    URBAN_OPPORTUNITY_RESEARCH_AGENT_INSTRUCTION,
    INFRA_MESSAGING_STRATEGIST_AGENT_INSTRUCTION,
    URBAN_AD_COPY_WRITER_AGENT_INSTRUCTION,
    INFRA_VISUAL_SUGGESTER_AGENT_INSTRUCTION,
    CAMPAIGN_BRIEF_FORMATTER_AGENT_INSTRUCTION,
    POLICY_VALIDATOR_AGENT_INSTRUCTION,
    COST_ESTIMATOR_AGENT_INSTRUCTION,
    IMPACT_MODELER_AGENT_INSTRUCTION,
    BLUEPRINT_DESIGN_AGENT_INSTRUCTION
)

# Create agents
urban_research_agent = LlmAgent(
    name="UrbanResearcher",
    model=MODEL_NAME,
    instruction=URBAN_OPPORTUNITY_RESEARCH_AGENT_INSTRUCTION,
    tools=[google_search],
    output_key="urban_research_summary"
)

policy_validator_agent = LlmAgent(
    name="PolicyValidator",
    model=MODEL_NAME,
    instruction=POLICY_VALIDATOR_AGENT_INSTRUCTION,
    output_key="policy_validation_summary"
)

cost_estimator_agent = LlmAgent(
    name="CostEstimator",
    model=MODEL_NAME,
    instruction=COST_ESTIMATOR_AGENT_INSTRUCTION,
    output_key="cost_estimate"
)

impact_modeler_agent = LlmAgent(
    name="ImpactModeler",
    model=MODEL_NAME,
    instruction=IMPACT_MODELER_AGENT_INSTRUCTION,
    output_key="impact_projection"
)

messaging_strategist_agent = LlmAgent(
    name="MessagingStrategist",
    model=MODEL_NAME,
    instruction=INFRA_MESSAGING_STRATEGIST_AGENT_INSTRUCTION,
    output_key="key_messaging"
)

ad_copy_writer_agent = LlmAgent(
    name="UrbanAdCopyWriter",
    model=MODEL_NAME,
    instruction=URBAN_AD_COPY_WRITER_AGENT_INSTRUCTION,
    output_key="urban_ad_copy_variations"
)

visual_suggester_agent = LlmAgent(
    name="VisualSuggester",
    model=MODEL_NAME,
    instruction=INFRA_VISUAL_SUGGESTER_AGENT_INSTRUCTION,
    output_key="visual_concepts"
)

blueprint_designer_agent = LlmAgent(
    name="BlueprintDesigner",
    model=MODEL_NAME,
    instruction=BLUEPRINT_DESIGN_AGENT_INSTRUCTION,
    output_key="blueprint_designer"
)

formatter_agent = LlmAgent(
    name="CampaignBriefFormatter",
    model=MODEL_NAME,
    instruction=CAMPAIGN_BRIEF_FORMATTER_AGENT_INSTRUCTION,
    output_key="final_campaign_brief"
)

# Create sequential agent pipeline
campaign_orchestrator = SequentialAgent(
    name="InfraCampaignAssistant",
    sub_agents=[
        urban_research_agent,
        policy_validator_agent,
        # cost_estimator_agent,
        # impact_modeler_agent,
        # messaging_strategist_agent,
        # ad_copy_writer_agent,
        visual_suggester_agent,
        blueprint_designer_agent,
        formatter_agent
    ]
)
