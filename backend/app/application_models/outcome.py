from enum import Enum


class AgentOutcome(str, Enum):
    """Controlled terminal outcomes of a workflow run (AG-022).

    Every run resolves to exactly one of these, so the response is never
    empty, technical, misleading, or a generic failure.
    """

    EXECUTE_SQL = "EXECUTE_SQL"
    ASK_CLARIFICATION = "ASK_CLARIFICATION"
    RETURN_HELP = "RETURN_HELP"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    REWRITE_AND_RETRY = "REWRITE_AND_RETRY"
    NO_RESULT_GUIDANCE = "NO_RESULT_GUIDANCE"
    SAFE_ERROR = "SAFE_ERROR"
