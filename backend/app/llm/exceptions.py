class LLMException(Exception):
    """Base exception class for all LLM Provider errors."""
    pass


class LLMConnectionError(LLMException):
    """Raised when connection to the LLM provider fails."""
    pass


class LLMTimeoutError(LLMException):
    """Raised when the LLM provider request times out."""
    pass


class LLMResponseError(LLMException):
    """Raised when the LLM provider returns an error status or invalid response."""
    pass
