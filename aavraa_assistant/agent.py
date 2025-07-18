from google.adk.agents import Agent
from google.adk.tools import google_search  # Import the tool
from aavraa_assistant.instructions import (AAVRAA_SEARCH_AGENT_INSTRUCTION)

root_agent = Agent(
   # A unique name for the agent.
   name="Aavraa",
   # The Large Language Model (LLM) that agent will use.
   model="gemini-2.0-flash-exp", # if this model does not work, try below
   #model="gemini-2.0-flash-live-001",
   # A short description of the agent's purpose.
   description = "I am Aavraa, your intelligent lifestyle guide. I help users shop smarter, move faster, discover nearby trends, and get things done effortlessly using taps or voice commands. Powered by AI, I provide personalized assistance tailored to each user’s needs." ,  # Instructions to set the agent's behavior.
   instruction=AAVRAA_SEARCH_AGENT_INSTRUCTION,
   # Add google_search tool to perform grounding with Google search.
   tools=[google_search],
)
