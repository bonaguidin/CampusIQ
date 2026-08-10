"""Central model routing for Gradus IQ AI roles."""

import os
from typing import Mapping, get_args

from .errors import AIConfigError
from .types import AgentRole


# TODO: Verify exact OpenRouter model identifiers before live API use.
# This remains a placeholder for orchestrator/report only -- see
# ROLES_VALIDATED_AT_STARTUP below for why those two are not yet blocking.
OPENROUTER_GEMINI_2_5_PRO = "TODO_OPENROUTER_MODEL_GEMINI_2_5_PRO"

# Validated against real OpenRouter calls in commit 557b45d (FIT/GAP/SHIFT/
# PROFESSOR_COMMENTS, 51/51 tests passing) — safe as a hardcoded default.
OPENROUTER_DEEPSEEK_R1 = "deepseek/deepseek-r1-0528"

# Flash-tier model for the role-research agent's tool-calling lookup loop
# (web_search rounds) -- kept cheap/fast since deepseek-r1-0528 above still
# handles final FIT/GAP/SHIFT narrative synthesis.
OPENROUTER_DEEPSEEK_V4_FLASH = "deepseek/deepseek-v4-flash"


MODEL_BY_ROLE: Mapping[AgentRole, str] = {
    "orchestrator": OPENROUTER_GEMINI_2_5_PRO,
    "career": OPENROUTER_DEEPSEEK_R1,
    "academic": OPENROUTER_DEEPSEEK_R1,
    # Repointed off the former TODO_OPENROUTER_MODEL_QWEN3_32B placeholder onto
    # the same Flash-tier model already validated for role_research.
    "parsing": OPENROUTER_DEEPSEEK_V4_FLASH,
    # Repointed off the former TODO_OPENROUTER_MODEL_GEMINI_2_5_FLASH
    # placeholder. Chat is turn-taking and latency-sensitive -- a student is
    # waiting on the reply -- so it deliberately does NOT reuse career/academic's
    # deepseek-r1-0528: measured against a real advisor-style turn, R1 took 12.1s
    # to Flash's 3.2s, and R1's reasoning traces scale with input while the chat
    # system message embeds the full student profile plus prior analysis on every
    # turn. Flash also has 1M context to R1's 164k, which that prompt needs.
    "chat": OPENROUTER_DEEPSEEK_V4_FLASH,
    "report": OPENROUTER_GEMINI_2_5_PRO,
    "role_research": OPENROUTER_DEEPSEEK_V4_FLASH,
}


ENV_BY_ROLE: Mapping[AgentRole, str] = {
    "orchestrator": "GRADUSIQ_MODEL_ORCHESTRATOR",
    "career": "GRADUSIQ_MODEL_CAREER",
    "academic": "GRADUSIQ_MODEL_ACADEMIC",
    "parsing": "GRADUSIQ_MODEL_PARSING",
    "chat": "GRADUSIQ_MODEL_CHAT",
    "report": "GRADUSIQ_MODEL_REPORT",
    "role_research": "GRADUSIQ_MODEL_ROLE_RESEARCH",
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


PLACEHOLDER_MODEL_PREFIX = "TODO_"

# Roles the running system actually resolves through get_model_for_role, and so
# the only ones whose model IDs are worth blocking startup over.
#
# Two roles are deliberately EXCLUDED. Neither is an oversight:
#
#   orchestrator, report -- reachable only through ai_services.call_agent,
#     which has no production caller today (its only references are its own
#     definition and tests/test_ai_phase1.py). Validating roles nobody
#     exercises would block startup for models nobody sends.
#
# `chat` used to be a third exclusion, on the grounds that the chat route
# passed an explicit model= argument ("@preset/chat") and
# OpenRouterClient._select_model returns an explicit model without ever
# consulting get_model_for_role -- so chat's MODEL_BY_ROLE entry was never
# resolved at runtime and its placeholder was unreachable. That reasoning was
# correct and the conclusion was still wrong: exempting chat from the only
# check that inspects model IDs is what let a nonexistent preset ship. The
# preset did not exist on the account and every chat call 404'd, on both the
# slug-addressed and /me routes, until api.py dropped the explicit model= and
# let chat resolve by role like everything else.
#
# KNOWN LIMIT, so nobody reads more assurance into this set than it offers:
# validate_configured_models is a TODO_ prefix test, not a reachability check.
# It would NOT have caught "@preset/chat", which is well-formed and simply does
# not exist upstream. It equally would not catch a typo'd model ID or a bad
# GRADUSIQ_MODEL_* override. Catching that class needs a probe against
# OpenRouter's model list or a pinned allowlist -- deliberately not done here,
# since it would add a network dependency to create_app().
#
# If either excluded role gains a call site that resolves its model by role,
# add it here and give it a real model ID at the same time.
ROLES_VALIDATED_AT_STARTUP: frozenset[str] = frozenset(
    {
        "career",
        "academic",
        "role_research",
        "parsing",
        "chat",
    }
)


def validate_configured_models(roles_in_use: set[str]) -> None:
    """Raise if any role in `roles_in_use` still resolves to a placeholder.

    Resolution goes through get_model_for_role, so this honors the same
    precedence real calls use: an env override wins over the hardcoded
    MODEL_BY_ROLE default. A role whose default is still a placeholder passes
    cleanly once GRADUSIQ_MODEL_<ROLE> supplies a real ID.

    Called at app construction so a bad model ID fails the deploy rather than
    surfacing as an opaque 502 on the first live request.
    """
    unresolved: list[str] = []
    for role in sorted(roles_in_use):
        model = get_model_for_role(role)
        if model.startswith(PLACEHOLDER_MODEL_PREFIX):
            unresolved.append(f"{role} -> {model}")

    if unresolved:
        raise AIConfigError(
            "Placeholder model ID(s) still configured for role(s) in use: "
            + "; ".join(unresolved)
            + ". Set a real OpenRouter model ID in MODEL_BY_ROLE, or supply one "
            "via the matching GRADUSIQ_MODEL_* environment variable."
        )
