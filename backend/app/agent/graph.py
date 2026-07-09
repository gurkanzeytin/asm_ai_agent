import logging

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agent.nodes.analyze_intent import AnalyzeIntentNode
from app.agent.nodes.generate_chat_response import GenerateChatResponseNode
from app.agent.nodes.generate_help import GenerateHelpNode
from app.agent.nodes.generate_clarification import GenerateClarificationNode
from app.agent.nodes.execute_sql import ExecuteSQLNode
from app.agent.nodes.generate_report import GenerateReportNode
from app.agent.nodes.generate_sql import GenerateSQLNode
from app.agent.nodes.retrieve_context import RetrieveContextNode
from app.agent.nodes.validate_sql import ValidateSQLNode
from app.agent.state import AgentState
from app.core.config import settings
from app.llm.interfaces import ILLMProvider
from app.services.interfaces import (
    IHelpService,
    IIntentClassifier,
    IPromptService,
    IWorkflowService,
)

logger = logging.getLogger(__name__)


def route_by_intent(state: AgentState) -> str:
    """Routing function analyzing state.intent to direct graph traversal.

    Falls back to 'database_query' if the confidence is below the configured threshold,
    and logs structured observability metrics including the workflow ID and timing details.
    """
    intent_res = state.intent
    if not intent_res:
        return "database_query"

    if intent_res.confidence < settings.INTENT_CONFIDENCE_THRESHOLD:
        decision = "database_query"
    else:
        decision = intent_res.intent.value

    # Extract timing of analysis node
    elapsed_ms = state.node_timings.get("analyze_intent", 0.0)

    logger.info(
        "Intent Router Decision: workflow_id=%s elapsed_ms=%.2f question=%s detected_intent=%s confidence=%.2f matched_rule=%s final_routing_decision=%s matched_keywords=%s",
        state.workflow_id or "unknown",
        elapsed_ms,
        state.question,
        intent_res.intent.value,
        intent_res.confidence,
        intent_res.reason or "none",
        decision,
        intent_res.matched_keywords,
    )
    return decision


from typing import Optional

class AgentGraphBuilder:
    """Builder class responsible for injecting services, instantiating nodes, and compiling LangGraph."""

    def __init__(
        self,
        prompt_service: IPromptService,
        workflow_service: IWorkflowService,
        intent_classifier: Optional[IIntentClassifier] = None,
        help_service: Optional[IHelpService] = None,
        llm_provider: Optional[ILLMProvider] = None,
    ):
        self.prompt_service = prompt_service
        self.workflow_service = workflow_service

        if intent_classifier is None:
            from app.services.intent_classifier import IntentClassifier
            intent_classifier = IntentClassifier()
        self.intent_classifier = intent_classifier

        if help_service is None:
            from app.services.help_service import HelpService
            help_service = HelpService()
        self.help_service = help_service

        if llm_provider is None:
            from app.llm.provider import LLMFactory
            llm_provider = LLMFactory.get_provider()
        self.llm_provider = llm_provider

    def build(self) -> CompiledStateGraph:
        """Assembles node topology and compiles the state graph."""
        logger.info("Starting agent graph construction via AgentGraphBuilder.")

        # 1. Instantiate workflow nodes
        analyze_intent_node = AnalyzeIntentNode(self.intent_classifier)
        chat_node = GenerateChatResponseNode(self.prompt_service, self.llm_provider)
        help_node = GenerateHelpNode(self.help_service)
        clarification_node = GenerateClarificationNode()

        retrieve_node = RetrieveContextNode(self.prompt_service)
        generate_node = GenerateSQLNode(self.workflow_service)
        validate_node = ValidateSQLNode()
        execute_node = ExecuteSQLNode(self.workflow_service)
        report_node = GenerateReportNode(self.workflow_service)

        # 2. Build StateGraph using the IAgentNode.execute method wrappers
        workflow = StateGraph(AgentState)

        workflow.add_node("analyze_intent", analyze_intent_node.execute)
        workflow.add_node("generate_chat_response", chat_node.execute)
        workflow.add_node("generate_help", help_node.execute)
        workflow.add_node("generate_clarification", clarification_node.execute)

        workflow.add_node("retrieve_context", retrieve_node.execute)
        workflow.add_node("generate_sql", generate_node.execute)
        workflow.add_node("validate_sql", validate_node.execute)
        workflow.add_node("execute_sql", execute_node.execute)
        workflow.add_node("generate_report", report_node.execute)

        # 3. Add Edges & Conditional Routing
        workflow.add_edge(START, "analyze_intent")

        workflow.add_conditional_edges(
            "analyze_intent",
            route_by_intent,
            {
                "database_query": "retrieve_context",
                "general_chat": "generate_chat_response",
                "help": "generate_help",
                "unknown": "generate_clarification",
            }
        )

        # Direct shortcuts to END
        workflow.add_edge("generate_chat_response", END)
        workflow.add_edge("generate_help", END)
        workflow.add_edge("generate_clarification", END)

        # Standard SQL execution pipeline
        workflow.add_edge("retrieve_context", "generate_sql")
        workflow.add_edge("generate_sql", "validate_sql")
        workflow.add_edge("validate_sql", "execute_sql")
        workflow.add_edge("execute_sql", "generate_report")
        workflow.add_edge("generate_report", END)

        logger.info("Agent graph constructed and compiled successfully.")
        return workflow.compile()

