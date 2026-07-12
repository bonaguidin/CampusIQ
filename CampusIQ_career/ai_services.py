"""Backward-compatible AI service helpers.

New code should use CampusIQ_career.ai.OpenRouterClient directly. This module
keeps the original call_agent() surface while routing through the canonical
OpenRouter client.
"""

from typing import Any, Mapping, Sequence

from CampusIQ_career.ai import AIConfigError, AIMessage, OpenRouterClient
from CampusIQ_career.ai.types import AgentRole


AGENT_ROLE_BY_NAME: Mapping[str, AgentRole] = {
    "fit": "career",
    "gap": "career",
    "shift": "career",
    "career": "career",
    "academic": "academic",
    "exam_gap": "academic",
    "study_guide": "academic",
    "course_cert_recommender": "academic",
    "professor_comments": "academic",
    "parser": "parsing",
    "parsing": "parsing",
    "cleanup": "parsing",
    "chat": "chat",
    "report": "report",
    "report_generator": "report",
    "orchestrator": "orchestrator",
    "full_analysis": "orchestrator",
}


def get_role_for_agent(agent_name: str) -> AgentRole:
    normalized = agent_name.strip().lower()
    try:
        return AGENT_ROLE_BY_NAME[normalized]
    except KeyError as exc:
        known = ", ".join(sorted(AGENT_ROLE_BY_NAME))
        raise AIConfigError(f"Unknown agent '{agent_name}'. Expected one of: {known}.") from exc


def call_agent(
    agent_name: str,
    messages: Sequence[AIMessage | Mapping[str, Any]],
    *,
    client: OpenRouterClient | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
    extra_body: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    """Call an AI agent and return the raw OpenRouter response JSON."""

    role = get_role_for_agent(agent_name)
    ai_client = client or OpenRouterClient()
    response = ai_client.complete(
        messages=messages,
        role=role,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        extra_body=extra_body,
    )
    return response.raw
