"""Shared exceptions for the job-posting diagnostic clients.

Mirrors GradusIQ_career/ai/errors.py's shape (AIConfigError / AIRequestError)
so a missing credential and a failed request stay distinguishable the same
way they are for the OpenRouter/Tavily clients: config problems are a setup
mistake, request failures carry a transient flag instead of being retried
automatically (this codebase has no retry/backoff anywhere -- see
openrouter_client.py's _send, which classifies and raises rather than
retrying).
"""


class JobPostingConfigError(Exception):
    """Raised when a required credential is missing or blank."""


class JobPostingRequestError(Exception):
    """Raised when a live request to a job-posting vendor fails.

    ``transient`` mirrors AIRequestError: True for connection errors,
    timeouts, 429, and 5xx -- the caller can decide whether that's worth a
    manual re-run. False for everything else (4xx other than 429), which is a
    request-shape or auth problem a re-run won't fix.
    """

    def __init__(self, message: str, *, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient
