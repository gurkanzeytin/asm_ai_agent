from enum import StrEnum


class AgentOutcome(StrEnum):
    """Controlled terminal outcomes of a workflow run (AG-022).

    Every run resolves to exactly one of these, so the response is never
    empty, technical, misleading, or a generic failure.
    """

    EXECUTE_SQL = "EXECUTE_SQL"
    SQL_ONLY = "SQL_ONLY"
    DATA_ONLY = "DATA_ONLY"
    VISUALIZATION_ONLY = "VISUALIZATION_ONLY"
    ASK_CLARIFICATION = "ASK_CLARIFICATION"
    RETURN_HELP = "RETURN_HELP"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    REWRITE_AND_RETRY = "REWRITE_AND_RETRY"
    NO_RESULT_GUIDANCE = "NO_RESULT_GUIDANCE"
    SAFE_ERROR = "SAFE_ERROR"
