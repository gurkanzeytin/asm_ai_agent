import logging
from typing import Any

from app.agent.state import AgentState
from app.agent.workflow import agent_graph

logger = logging.getLogger(__name__)


class ReportingService:
    """Service to handle reporting agent lifecycle triggers."""

    @staticmethod
    async def generate_report(query: str) -> dict[str, Any]:
        """Runs the agent workflow to produce an analytical report.

        Args:
            query: Natural language query.

        Returns:
            dict: Synthesis containing query, generated SQL, results, and markdown report.
        """
        logger.info(f"ReportingService: Triggering agent pipeline for query: {query}")

        initial_state: AgentState = {
            "messages": [],
            "report_query": query,
            "schema_context": None,
            "sql_query": None,
            "sql_valid": None,
            "query_result": None,
            "report_output": None,
            "error": None,
        }

        final_state = await agent_graph.ainvoke(initial_state)

        return {
            "query": query,
            "sql_query": final_state.get("sql_query"),
            "query_result": final_state.get("query_result"),
            "report": final_state.get("report_output"),
            "error": final_state.get("error"),
        }
