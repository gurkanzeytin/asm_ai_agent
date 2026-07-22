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


class LLMAuthenticationError(LLMConnectionError):
    """Raised when the LLM provider rejects the configured API key/credentials.

    Subclasses LLMConnectionError so existing callers that catch the broader
    connection failure category still handle authentication failures correctly.
    """
    pass


class LLMRateLimitError(LLMException):
    """Raised when the LLM provider reports that its rate limit has been exceeded."""
    pass
