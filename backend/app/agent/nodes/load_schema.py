import logging

from app.agent.state import AgentState

logger = logging.getLogger(__name__)


async def load_schema_node(state: AgentState) -> dict:
    """Loads the database schema catalog and populates the state context.

    Args:
        state: Active agent lifecycle state.

    Returns:
        dict: State update dictionary containing the schema context.
    """
    logger.info("Running agent node: load_schema")

    # Scaffolding placeholder: In production, query database metadata catalogs
    # or system tables (such as sqlite_master or information_schema)
    mock_schema_context = (
        "Table: transactions (\n"
        "  id INT PRIMARY KEY,\n"
        "  amount FLOAT,\n"
        "  created_at TIMESTAMP\n"
        ")"
    )

    return {"schema_context": mock_schema_context}
