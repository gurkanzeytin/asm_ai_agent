"""Per-model pipeline assembly and LLM call instrumentation.

Builds an isolated copy of the production workflow (same classes, dependency-
injected provider) for each candidate model. Production modules are imported,
never modified.
"""

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.llm.exceptions import LLMTimeoutError
from app.llm.interfaces import ILLMProvider
from app.llm.schemas import LLMResponse

logger = logging.getLogger(__name__)


@dataclass
class LLMCallLog:
    """Counters accumulated across every LLM call made through the wrapper."""

    calls: int = 0
    timeouts: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    finish_reasons: list[str] = field(default_factory=list)

    def snapshot(self) -> tuple[int, int, int, int, int]:
        return (
            self.calls,
            self.timeouts,
            self.prompt_tokens,
            self.completion_tokens,
            len(self.finish_reasons),
        )


class RecordingProvider(ILLMProvider):
    """Transparent ILLMProvider wrapper that records call metrics for the benchmark."""

    def __init__(self, inner: ILLMProvider):
        self.inner = inner
        self.log = LLMCallLog()

    async def generate(self, prompt: str, think: bool = True, options: dict | None = None) -> LLMResponse:
        self.log.calls += 1
        try:
            response = await self.inner.generate(prompt, think=think, options=options)
        except LLMTimeoutError:
            self.log.timeouts += 1
            self.log.finish_reasons.append("timeout")
            raise
        self.log.prompt_tokens += response.prompt_tokens or 0
        self.log.completion_tokens += response.completion_tokens or 0
        self.log.finish_reasons.append(response.finish_reason or "unknown")
        return response

    async def stream_generate(self, prompt: str):
        return self.inner.stream_generate(prompt)

    async def embed(self, text: str) -> list[float]:
        return await self.inner.embed(text)

    async def health_check(self) -> bool:
        return await self.inner.health_check()

    def get_metadata(self) -> dict[str, Any]:
        return self.inner.get_metadata()

    async def close(self) -> None:
        await self.inner.close()


def installed_ollama_models(base_url: str) -> set[str]:
    """Returns installed model names (full and base, e.g. {'qwen3:8b', 'qwen3'})."""
    try:
        response = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=5.0)
        response.raise_for_status()
        names: set[str] = set()
        for model in response.json().get("models", []):
            name = str(model.get("name", ""))
            if name:
                names.add(name)
                names.add(name.split(":", 1)[0])
        return names
    except Exception as e:
        logger.warning(f"Could not query Ollama for installed models: {e}")
        return set()


def is_model_available(model: str, installed: set[str]) -> bool:
    return model in installed or model.split(":", 1)[0] in installed


@dataclass
class ModelPipeline:
    """A fully wired workflow pipeline bound to one candidate model."""

    model: str
    reporting_service: Any
    provider: RecordingProvider


def build_pipeline(model: str) -> ModelPipeline:
    """Assembles the production workflow graph with the given Ollama model injected.

    Mirrors app.bootstrap.AppContainer wiring; shares nothing mutable with the
    running application.
    """
    from app.agent.graph import AgentGraphBuilder
    from app.database.session import SessionLocal, engine
    from app.database_intelligence.cache import SchemaCache
    from app.database_intelligence.inspector import DatabaseInspector
    from app.database_intelligence.retriever import SchemaRetriever
    from app.llm.ollama import OllamaProvider
    from app.parsers.output_parser import OutputParser
    from app.prompts.loader import prompt_loader
    from app.prompts.renderer import prompt_renderer
    from app.repositories.base import ScopedAnalyticalRepository
    from app.services.execution_service import ExecutionService
    from app.services.help_service import HelpService
    from app.services.intent_classifier import IntentClassifier
    from app.services.prompt_service import PromptService
    from app.services.report_service import ReportService
    from app.services.reporting_service import ReportingService
    from app.services.sql_service import SQLService
    from app.services.workflow_service import WorkflowService
    from app.sql_validator.validator import SQLValidator

    provider = RecordingProvider(
        OllamaProvider(model=model, validate_embedding_model=False)
    )

    inspector = DatabaseInspector(engine)
    schema_cache = SchemaCache(inspector)
    schema_retriever = SchemaRetriever(schema_cache=schema_cache)
    repository = ScopedAnalyticalRepository(SessionLocal)

    prompt_service = PromptService(
        schema_cache=schema_cache,
        schema_retriever=schema_retriever,
        prompt_loader=prompt_loader,
        prompt_renderer=prompt_renderer,
    )
    sql_validator = SQLValidator()
    sql_service = SQLService(
        llm_provider=provider,
        output_parser=OutputParser(),
        sql_validator=sql_validator,
    )
    execution_service = ExecutionService(repository=repository, sql_validator=sql_validator)
    report_service = ReportService(prompt_service=prompt_service, llm_provider=provider)
    workflow_service = WorkflowService(
        prompt_service=prompt_service,
        sql_service=sql_service,
        report_service=report_service,
        execution_service=execution_service,
    )
    graph = AgentGraphBuilder(
        prompt_service=prompt_service,
        workflow_service=workflow_service,
        intent_classifier=IntentClassifier(),
        help_service=HelpService(),
        llm_provider=provider,
    ).build()

    return ModelPipeline(
        model=model,
        reporting_service=ReportingService(agent_graph=graph),
        provider=provider,
    )
