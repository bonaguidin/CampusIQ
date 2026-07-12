"""Lightweight shared AI request and response types."""

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Sequence


AgentRole = Literal[
    "orchestrator",
    "career",
    "academic",
    "parsing",
    "chat",
    "report",
]


@dataclass(frozen=True)
class AIMessage:
    role: str
    content: str


@dataclass(frozen=True)
class AIRequest:
    messages: Sequence[AIMessage | Mapping[str, Any]]
    role: AgentRole | str | None = None
    model: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None


@dataclass(frozen=True)
class AIResponse:
    text: str
    raw: Mapping[str, Any]
    model: str
    provider: str = "openrouter"
    metadata: Mapping[str, Any] = field(default_factory=dict)
