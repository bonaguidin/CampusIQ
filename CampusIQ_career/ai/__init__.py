"""Canonical AI integration utilities for Campus IQ."""

from .errors import AIConfigError, AIRequestError, AIResponseParseError
from .openrouter_client import OpenRouterClient
from .types import AIMessage, AIRequest, AIResponse, AgentRole

__all__ = [
    "AIConfigError",
    "AIMessage",
    "AIRequest",
    "AIRequestError",
    "AIResponse",
    "AIResponseParseError",
    "AgentRole",
    "OpenRouterClient",
]
