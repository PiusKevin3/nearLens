# from . import agent

from aavraa_assistant.agent import aavraa_orchestrator,research_agent

# Expose both for external runners
root_agent = aavraa_orchestrator
research_agent = research_agent

