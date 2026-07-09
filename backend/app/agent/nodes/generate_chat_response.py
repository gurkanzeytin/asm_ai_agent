import logging
from pathlib import Path
import time

from app.agent.nodes.node_interface import IAgentNode
from app.agent.state import AgentState
from app.application_models.generated_report import GeneratedReport
from app.core.config import settings
from app.llm.interfaces import ILLMProvider
from app.services.interfaces import IPromptService

logger = logging.getLogger(__name__)


class GenerateChatResponseNode(IAgentNode):
    """Workflow node responsible for generating conversational answers to general chat user queries.

    Bypasses database inspections entirely. Instantly returns a static greeting if sub_intent
    is identified as greeting, saving latency and token execution costs.
    """

    def __init__(
        self,
        prompt_service: IPromptService,
        llm_provider: ILLMProvider,
        greetings_file_path: Path | None = None,
    ):
        """Initializes the node with prompt service and LLM provider.

        Args:
            prompt_service: Service to load system prompt templates.
            llm_provider: Client for LLM generation.
            greetings_file_path: Optional path to greetings.md.
        """
        self.prompt_service = prompt_service
        self.llm_provider = llm_provider

        if greetings_file_path is None:
            greetings_file_path = Path(__file__).parent.parent.parent / "resources" / "greetings.md"
        self._greetings_file_path = greetings_file_path
        self._cached_greeting = None

    async def execute(self, state: AgentState) -> AgentState:
        logger.info("GenerateChatResponseNode execution started.")
        start_time = time.perf_counter()

        try:
            # Single check: check if already classified as greeting by IntentClassifier
            is_greeting = (
                state.intent
                and state.intent.metadata.get("sub_intent") == "greeting"
            )

            if is_greeting:
                logger.info("Chat query classified as greeting. Bypassing LLM call.")
                response_text = self._get_greeting_text()
                model_name = "static_resource"
                latency_ms = 0.0
            else:
                # Normal general chat: compile system prompt and run LLM
                system_prompt = await self.prompt_service.render_prompt("system_prompt.md", state.question, {})
                prompt = f"{system_prompt}\n\nUser: {state.question}\nAssistant:"

                llm_response = await self.llm_provider.generate(prompt)
                response_text = llm_response.content
                model_name = llm_response.model
                latency_ms = llm_response.latency_ms

            meta = self.llm_provider.get_metadata()
            provider_name = meta.get("provider", "unknown") if not is_greeting else "static"

            report_dto = GeneratedReport(
                title="Chat Response",
                markdown=response_text,
                provider=provider_name,
                model=model_name,
                latency_ms=latency_ms,
            )

            logger.info("GenerateChatResponseNode completed successfully.")
            duration = (time.perf_counter() - start_time) * 1000

            return state.model_copy(
                update={
                    "generated_report": report_dto,
                    "current_node": "generate_chat_response",
                    "completed_nodes": state.completed_nodes + ["generate_chat_response"],
                    "duration_ms": state.duration_ms + duration,
                    "node_timings": {**state.node_timings, "generate_chat_response": duration},
                }
            )

        except Exception as e:
            logger.error(f"GenerateChatResponseNode execution failed: {e}")
            duration = (time.perf_counter() - start_time) * 1000

            return state.model_copy(
                update={
                    "errors": state.errors + [f"GenerateChatResponseNode failed: {e}"],
                    "current_node": "generate_chat_response",
                    "duration_ms": state.duration_ms + duration,
                    "node_timings": {**state.node_timings, "generate_chat_response": duration},
                }
            )

    def _get_greeting_text(self) -> str:
        """Loads default greeting markdown from disk, with hot-reloading in dev mode."""
        if settings.DEBUG:
            return self._read_greetings_file()

        if self._cached_greeting is None:
            self._cached_greeting = self._read_greetings_file()
        return self._cached_greeting

    def _read_greetings_file(self) -> str:
        """Reads greetings.md from disk with fallback."""
        try:
            return self._greetings_file_path.read_text(encoding="utf-8").strip()
        except Exception:
            return "Hello! I am your ASM AI assistant. How can I help you today?"
