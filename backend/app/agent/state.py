from collections.abc import Sequence
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """Type definition of the state tracker passed across agent processing nodes."""

    messages: Annotated[Sequence[BaseMessage], add_messages]
    report_query: str
    schema_context: str | None
    sql_query: str | None
    sql_valid: bool | None
    query_result: list[dict] | None
    report_output: str | None
    error: str | None
