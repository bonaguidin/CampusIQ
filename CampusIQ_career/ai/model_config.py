"""Central model routing for Campus IQ AI roles."""

import os
from typing import Mapping, get_args

from .errors import AIConfigError
from .types import AgentRole


# TODO: Verify exact OpenRouter model identifiers before live API use.
OPENROUTER_GEMINI_2_5_PRO = "TODO_OPENROUTER_MODEL_GEMINI_2_5_PRO"
OPENROUTER_QWEN3_32B = "TODO_OPENROUTER_MODEL_QWEN3_32B"
OPENROUTER_GEMINI_2_5_FLASH = "TODO_OPENROUTER_MODEL_GEMINI_2_5_FLASH"

# Validated against real OpenRouter calls in commit 557b45d (FIT/GAP/SHIFT/
# PROFESSOR_COMMENTS, 51/51 tests passing) — safe as a hardcoded default.
OPENROUTER_DEEPSEEK_R1 = "deepseek/deepseek-r1-0528"


MODEL_BY_ROLE: Mapping[AgentRole, str] = {
    "orchestrator": OPENROUTER_GEMINI_2_5_PRO,
    "career": OPENROUTER_DEEPSEEK_R1,
    "academic": OPENROUTER_DEEPSEEK_R1,
    "parsing": OPENROUTER_QWEN3_32B,
    "chat": OPENROUTER_GEMINI_2_5_FLASH,
    "report": OPENROUTER_GEMINI_2_5_PRO,
}


ENV_BY_ROLE: Mapping[AgentRole, str] = {
    "orchestrator": "CAMPUSIQ_MODEL_ORCHESTRATOR",
    "career": "CAMPUSIQ_MODEL_CAREER",
    "academic": "CAMPUSIQ_MODEL_ACADEMIC",
    "parsing": "CAMPUSIQ_MODEL_PARSING",
    "chat": "CAMPUSIQ_MODEL_CHAT",
    "report": "CAMPUSIQ_MODEL_REPORT",
}


def normalize_agent_role(role: AgentRole | str) -> AgentRole:
    valid_roles = set(get_args(AgentRole))
    normalized = role.lower() if isinstance(role, str) else role
    if normalized not in valid_roles:
        valid = ", ".join(sorted(valid_roles))
        raise AIConfigError(f"Unknown agent role '{role}'. Expected one of: {valid}.")
    return normalized


def get_model_for_role(role: AgentRole | str) -> str:
    normalized = normalize_agent_role(role)
    override = os.getenv(ENV_BY_ROLE[normalized])
    if override and override.strip():
        return override.strip()
    return MODEL_BY_ROLE[normalized]
