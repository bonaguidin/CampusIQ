"""AI-specific exceptions."""


class AIConfigError(Exception):
    """Raised when AI configuration is missing or invalid."""


class AIRequestError(Exception):
    """Raised when an AI provider request fails."""


class AIResponseParseError(Exception):
    """Raised when an AI provider response cannot be parsed safely."""
