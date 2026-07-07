import logging

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agent.nodes.generate_sql import GenerateSQLNode
from app.agent.nodes.retrieve_context import RetrieveContextNode
from app.agent.nodes.validate_sql import ValidateSQLNode
from app.agent.state import AgentState
from app.database.session import engine
from app.database_intelligence.cache import SchemaCache
from app.database_intelligence.inspector import DatabaseInspector
from app.database_intelligence.retriever import SchemaRetriever
from app.llm.provider import LLMFactory
from app.parsers import OutputParser
from app.prompts.loader import prompt_loader
from app.prompts.renderer import prompt_renderer
from app.services import PromptService, ReportService, SQLService, WorkflowService
from app.services.interfaces import IPromptService, IWorkflowService
from app.sql_validator import SQLValidator

logger = logging.getLogger(__name__)


class AgentGraphBuilder:
    """Builder class responsible for injecting services, instantiating nodes, and compiling LangGraph."""

    def __init__(self, prompt_service: IPromptService, workflow_service: IWorkflowService):
        self.prompt_service = prompt_service
        self.workflow_service = workflow_service

    def build(self) -> CompiledStateGraph:
        """Assembles node topology and compiles the linear state graph."""
        logger.info("Starting agent graph construction via AgentGraphBuilder.")

        # 1. Instantiate workflow nodes
        retrieve_node = RetrieveContextNode(self.prompt_service)
        generate_node = GenerateSQLNode(self.prompt_service, self.workflow_service)
        validate_node = ValidateSQLNode()

        # 2. Build StateGraph using the IAgentNode.execute method wrappers
        workflow = StateGraph(AgentState)

        workflow.add_node("retrieve_context", retrieve_node.execute)
        workflow.add_node("generate_sql", generate_node.execute)
        workflow.add_node("validate_sql", validate_node.execute)

        workflow.add_edge(START, "retrieve_context")
        workflow.add_edge("retrieve_context", "generate_sql")
        workflow.add_edge("generate_sql", "validate_sql")
        workflow.add_edge("validate_sql", END)

        logger.info("Agent graph constructed and compiled successfully.")
        return workflow.compile()


# --- Default compiled graph instance for application ingestion ---

# Initialize DI stack
inspector = DatabaseInspector(engine)
schema_cache = SchemaCache(inspector)
schema_retriever = SchemaRetriever()

prompt_service_impl = PromptService(
    schema_cache=schema_cache,
    schema_retriever=schema_retriever,
    prompt_loader=prompt_loader,
    prompt_renderer=prompt_renderer,
)

llm_provider = LLMFactory.get_provider()
output_parser = OutputParser()
sql_validator = SQLValidator()

sql_service_impl = SQLService(
    llm_provider=llm_provider,
    output_parser=output_parser,
    sql_validator=sql_validator,
)

report_service_impl = ReportService(
    prompt_service=prompt_service_impl,
    llm_provider=llm_provider,
)

workflow_service_impl = WorkflowService(
    prompt_service=prompt_service_impl,
    sql_service=sql_service_impl,
    report_service=report_service_impl,
)

# Instantiate builder and compile default singleton graph
builder = AgentGraphBuilder(
    prompt_service=prompt_service_impl,
    workflow_service=workflow_service_impl,
)
agent_graph = builder.build()
