import logging

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agent.nodes.execute_sql import ExecuteSQLNode
from app.agent.nodes.generate_report import GenerateReportNode
from app.agent.nodes.generate_sql import GenerateSQLNode
from app.agent.nodes.retrieve_context import RetrieveContextNode
from app.agent.nodes.validate_sql import ValidateSQLNode
from app.agent.state import AgentState
from app.services.interfaces import IPromptService, IWorkflowService

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
        execute_node = ExecuteSQLNode(self.workflow_service)
        report_node = GenerateReportNode(self.workflow_service)

        # 2. Build StateGraph using the IAgentNode.execute method wrappers
        workflow = StateGraph(AgentState)

        workflow.add_node("retrieve_context", retrieve_node.execute)
        workflow.add_node("generate_sql", generate_node.execute)
        workflow.add_node("validate_sql", validate_node.execute)
        workflow.add_node("execute_sql", execute_node.execute)
        workflow.add_node("generate_report", report_node.execute)

        workflow.add_edge(START, "retrieve_context")
        workflow.add_edge("retrieve_context", "generate_sql")
        workflow.add_edge("generate_sql", "validate_sql")
        workflow.add_edge("validate_sql", "execute_sql")
        workflow.add_edge("execute_sql", "generate_report")
        workflow.add_edge("generate_report", END)

        logger.info("Agent graph constructed and compiled successfully.")
        return workflow.compile()
