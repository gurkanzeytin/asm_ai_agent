import logging

from app.agent.state import AgentState
from app.validators.sql_validator import SQLValidator

logger = logging.getLogger(__name__)


async def validate_sql_node(state: AgentState) -> dict:
    """Validates the security profile of the generated SQL.

    Args:
        state: Active agent lifecycle state.

    Returns:
        dict: State update dictionary containing validation status or errors.
    """
    logger.info("Running agent node: validate_sql")

    sql_query = state.get("sql_query")
    if not sql_query:
        return {"sql_valid": False, "error": "No SQL query found for validation."}

    # Check if the query is a safe read-only query
    is_safe = SQLValidator.is_safe_query(sql_query)

    if not is_safe:
        logger.warning(f"Malicious query pattern detected: {sql_query}")
        return {
            "sql_valid": False,
            "error": "Query validation failed. Write operations are prohibited.",
        }

    return {"sql_valid": True}
