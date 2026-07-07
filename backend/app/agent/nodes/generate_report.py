import logging

from app.agent.state import AgentState
from app.llm.ollama import OllamaProvider
from app.llm.prompt_builder import PromptBuilder

logger = logging.getLogger(__name__)


async def generate_report_node(state: AgentState) -> dict:
    """Uses LLM to summarize SQL results into a structured markdown report.

    Args:
        state: Active agent lifecycle state.

    Returns:
        dict: State update dictionary containing final markdown report.
    """
    logger.info("Running agent node: generate_report")

    if state.get("error"):
        return {"error": "Skipping report generation due to previous errors."}

    query = state.get("report_query", "")
    sql = state.get("sql_query", "")
    results = state.get("query_result", [])

    llm = OllamaProvider()

    try:
        system_prompt = PromptBuilder.load_prompt("system_prompt.md")
        report_prompt = PromptBuilder.load_prompt(
            "report_generation.md", question=query, sql_query=sql, query_result=str(results)
        )

        full_prompt = f"{system_prompt}\n\n{report_prompt}"
        raw_report = await llm.generate(full_prompt)

        # Format mock report outputs if simulation fallback triggered
        if "[Simulated" in raw_report:
            raw_report = (
                f"## Analytical Report: {query}\n\n"
                f"### Query Executed\n```sql\n{sql}\n```\n\n"
                f"### Key Findings\n- Database returned {len(results)} rows.\n"
                f"- First result: `{results[0] if results else '{}'}`"
            )

        return {"report_output": raw_report}
    except Exception as e:
        logger.error(f"Report synthesis node error: {e}")
        return {"error": f"Failed to compile report narrative: {str(e)}"}
