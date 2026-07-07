import logging

from app.agent.state import AgentState
from app.services.sql_service import SQLService

logger = logging.getLogger(__name__)


async def execute_query_node(state: AgentState) -> dict:
    """Executes the verified read-only SQL query against the target database.

    Args:
        state: Active agent lifecycle state.

    Returns:
        dict: State update dictionary containing database query results.
    """
    logger.info("Running agent node: execute_query")

    if not state.get("sql_valid"):
        return {"error": "Execution aborted due to failed query safety checks."}

    query = state.get("sql_query")
    if not query:
        return {"error": "No SQL query found for database execution."}

    try:
        # Abstract database fetch logic inside SQLService
        results = await SQLService.execute_query(query)
        return {"query_result": results}
    except Exception as e:
        logger.error(f"Database execution node error: {e}")
        return {"error": f"Failed to retrieve database records: {str(e)}"}
