from langgraph.graph import END, StateGraph

from app.agent.nodes import (
    analyze_question_node,
    execute_query_node,
    generate_report_node,
    generate_sql_node,
    load_schema_node,
    validate_sql_node,
)
from app.agent.state import AgentState


def create_agent_workflow() -> StateGraph:
    """Links single responsibility agent nodes into a functional graph structure."""
    workflow = StateGraph(AgentState)

    # Register workflow nodes
    workflow.add_node("analyze_question", analyze_question_node)
    workflow.add_node("load_schema", load_schema_node)
    workflow.add_node("generate_sql", generate_sql_node)
    workflow.add_node("validate_sql", validate_sql_node)
    workflow.add_node("execute_query", execute_query_node)
    workflow.add_node("generate_report", generate_report_node)

    # Setup linear orchestration chain
    workflow.set_entry_point("analyze_question")
    workflow.add_edge("analyze_question", "load_schema")
    workflow.add_edge("load_schema", "generate_sql")
    workflow.add_edge("generate_sql", "validate_sql")
    workflow.add_edge("validate_sql", "execute_query")
    workflow.add_edge("execute_query", "generate_report")
    workflow.add_edge("generate_report", END)

    return workflow


# Compiled workflow interface
agent_graph = create_agent_workflow().compile()
