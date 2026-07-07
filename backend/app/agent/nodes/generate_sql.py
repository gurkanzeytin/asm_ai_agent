import logging

from app.agent.state import AgentState
from app.llm.ollama import OllamaProvider
from app.llm.parser import OutputParser
from app.llm.prompt_builder import PromptBuilder

logger = logging.getLogger(__name__)


async def generate_sql_node(state: AgentState) -> dict:
    """Orchestrates prompts loading, LLM request execution, and SQL parsing.

    Args:
        state: Active agent lifecycle state.

    Returns:
        dict: State update dictionary containing the parsed SQL query.
    """
    logger.info("Running agent node: generate_sql")

    # Initialize the LLM interface
    llm = OllamaProvider()

    # Load external prompt templates
    try:
        system_prompt = PromptBuilder.load_prompt("system_prompt.md")
        sql_prompt = PromptBuilder.load_prompt(
            "sql_generation.md",
            schema_description=state.get("schema_context", ""),
            question=state.get("report_query", ""),
        )

        full_prompt = f"{system_prompt}\n\n{sql_prompt}"

        # Invoke generation
        raw_response = await llm.generate(full_prompt)

        # Parse the raw response to clean SQL code
        sql_query = OutputParser.parse_sql(raw_response)

        # Fallback query if mock placeholder response detected
        if "[Simulated" in raw_response:
            sql_query = "SELECT * FROM transactions LIMIT 5;"

    except Exception as e:
        logger.error(f"SQL generation node error: {e}")
        sql_query = "SELECT * FROM transactions LIMIT 5;"  # Safe fallback block

    return {"sql_query": sql_query}
