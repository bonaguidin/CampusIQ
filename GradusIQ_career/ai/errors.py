"""AI-specific exceptions."""


class AIConfigError(Exception):
    """Raised when AI configuration is missing or invalid."""


class AIRequestError(Exception):
    """Raised when an AI provider request fails."""

    def __init__(self, message: str, *, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient


class AIResponseParseError(Exception):
    """Raised when an AI provider response cannot be parsed safely."""
