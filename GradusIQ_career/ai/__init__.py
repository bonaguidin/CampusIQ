"""Canonical AI integration utilities for Gradus IQ."""

from .context import AgentContext, GroundingMetadata
from .contracts import ChatOutput, FitOutput, GapOutput, ShiftOutput
from .errors import AIConfigError, AIRequestError, AIResponseParseError
from .openrouter_client import OpenRouterClient
from .runtime import AIRuntime, AIExecutionTrace
from .types import AIMessage, AIRequest, AIResponse, AgentRole

__all__ = [
    "AIConfigError",
    "AgentContext",
    "GroundingMetadata",
    "ChatOutput",
    "FitOutput",
    "GapOutput",
    "ShiftOutput",
    "AIRuntime",
    "AIExecutionTrace",
    "AIMessage",
    "AIRequest",
    "AIRequestError",
    "AIResponse",
    "AIResponseParseError",
    "AgentRole",
    "OpenRouterClient",
]
