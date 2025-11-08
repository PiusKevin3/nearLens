from google.adk.runners import InMemoryRunner
from google.adk.agents.run_config import RunConfig
from google.genai.types import Part, Content, Blob

class WorkerAgentTool:
    def __init__(self, app_name, agent):
        self.app_name = app_name
        self.agent = agent

    async def __call__(self, user_query: str) -> dict:
        """
        Launches a separate session runner for the worker agent to fetch JSON item results.
        Returns raw tool-compatible output to the orchestrator agent.
        """
        runner = InMemoryRunner(app_name=self.app_name, agent=self.agent)

        session = await runner.session_service.create_session(
            app_name=self.app_name, user_id="subagent"
        )
        run_config = RunConfig(response_modalities=["TEXT"])  # No audio here
        result = await runner.run_once(
            session=session,
            input_parts=[Part.from_text(user_query)],
            run_config=run_config,
        )
        return result.output  # This should be JSON (validated by worker agent schema)
