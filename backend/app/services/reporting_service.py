import logging
from typing import Any

from app.agent import AgentState, agent_graph

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

        initial_state = AgentState(question=query)

        # Run compiled LangGraph workflow pipeline
        final_state = await agent_graph.ainvoke(initial_state)

        generated_sql_dto = final_state.get("generated_sql")
        errors = final_state.get("errors", [])
        error_msg = errors[0] if errors else None

        sql_query = generated_sql_dto.sql if generated_sql_dto else None

        return {
            "query": query,
            "sql_query": sql_query,
            "query_result": None,
            "report": None,
            "error": error_msg,
        }
