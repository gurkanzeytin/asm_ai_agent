import logging

from app.agent.graph import AgentGraphBuilder
from app.database.session import SessionLocal, engine
from app.database_intelligence.cache import SchemaCache
from app.database_intelligence.inspector import DatabaseInspector
from app.database_intelligence.retriever import SchemaRetriever
from app.llm.provider import LLMFactory
from app.parsers.output_parser import OutputParser
from app.prompts.loader import prompt_loader
from app.prompts.renderer import prompt_renderer
from app.repositories.base import ScopedAnalyticalRepository
from app.services.execution_service import ExecutionService
from app.services.prompt_service import PromptService
from app.services.report_service import ReportService
from app.services.reporting_service import ReportingService
from app.services.sql_service import SQLService
from app.services.workflow_service import WorkflowService
from app.services.help_service import HelpService
from app.services.intent_classifier import IntentClassifier
from app.sql_validator.validator import SQLValidator

logger = logging.getLogger(__name__)


class AppContainer:
    """Centralized Dependency Injection Container for development, testing, and production workflows."""

    def __init__(self):
        logger.info("Initializing AppContainer dependencies...")

        # 1. Database & Schema Discovery Infrastructure
        self.engine = engine
        self.inspector = DatabaseInspector(self.engine)
        self.schema_cache = SchemaCache(self.inspector)
        self.schema_retriever = SchemaRetriever(schema_cache=self.schema_cache)

        # Scoped Repository mapping transient connection lifetimes dynamically
        self.repository = ScopedAnalyticalRepository(SessionLocal)

        # 2. Prompt Management Infrastructure
        self.prompt_loader = prompt_loader
        self.prompt_renderer = prompt_renderer

        # 3. Prompt Application Service
        self.prompt_service = PromptService(
            schema_cache=self.schema_cache,
            schema_retriever=self.schema_retriever,
            prompt_loader=self.prompt_loader,
            prompt_renderer=self.prompt_renderer,
        )

        # 4. LLM, Parsers, and Validator Infrastructure
        self.llm_provider = LLMFactory.get_provider()
        self.output_parser = OutputParser()
        self.sql_validator = SQLValidator()

        # 5. SQL generation and safety checking service
        self.sql_service = SQLService(
            llm_provider=self.llm_provider,
            output_parser=self.output_parser,
            sql_validator=self.sql_validator,
        )

        # SQL Execution service
        self.execution_service = ExecutionService(
            repository=self.repository,
            sql_validator=self.sql_validator,
        )

        # 6. Narrative Report generation service
        self.report_service = ReportService(
            prompt_service=self.prompt_service,
            llm_provider=self.llm_provider,
        )

        # 7. Workflow coordination service
        self.workflow_service = WorkflowService(
            prompt_service=self.prompt_service,
            sql_service=self.sql_service,
            report_service=self.report_service,
            execution_service=self.execution_service,
        )

        # 8. Help and Intent Classification services
        self.help_service = HelpService()
        self.intent_classifier = IntentClassifier()

        # 9. Agent State Graph Builder
        self.agent_graph_builder = AgentGraphBuilder(
            prompt_service=self.prompt_service,
            workflow_service=self.workflow_service,
            intent_classifier=self.intent_classifier,
            help_service=self.help_service,
            llm_provider=self.llm_provider,
        )
        self.agent_graph = self.agent_graph_builder.build()

        # 9. Reporting Service — top-level API entry point backed by compiled agent graph
        self.reporting_service = ReportingService(
            agent_graph=self.agent_graph,
        )
        logger.info("AppContainer initialized successfully.")


# Central singleton container instance
container = AppContainer()
