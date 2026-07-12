"""Live role-requirements lookup agent (web_search tool loop).

Stage 1 of the role-research build: the tool-calling control loop and output
validation, exercised against an injected client (mirroring the ``client=``
mock-injection style used in ``tests/test_career_features.py``). The
``web_search`` tool is stubbed here -- real search wiring, file-based caching,
and the ``model_config.py`` "role_research" role land in Stage 2. Wiring this
into ``GapRunner.role_requirements_for()`` lands in Stage 3.

This module never raises: any failure (timeout, malformed JSON, unknown SOC
code, request/config error) returns ``None`` so ``gap.py`` can fall back to
the static ``data/role_requirements.json`` lookup silently. Only the module's
one log line records which path (``agent`` vs. ``static_fallback``) served a
given lookup, so fallback frequency is visible during demo testing.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Mapping

from CampusIQ_career.ai import AIConfigError, AIRequestError, AIResponseParseError, OpenRouterClient
from CampusIQ_career.ai.parser import parse_ai_json_response

logger = logging.getLogger(__name__)

# Flash-tier lookup model for the tool-calling research loop. Kept local (not
# in model_config.py's MODEL_BY_ROLE) until Stage 2 adds a "role_research"
# AgentRole there -- this constant moves at that point.
_LOOKUP_MODEL = "deepseek/deepseek-v4-flash"

# Max number of tool-call round-trips before the loop aborts (Stage-1 spec: 3).
_MAX_TOOL_ROUNDS = 3
# Wall-clock budget for the whole research phase, checked between rounds.
_TIME_BUDGET_SECONDS = 90.0
# Per-call timeout for the Flash-tier lookup model -- explicitly NOT the 300s
# override api.py uses for DeepSeek R1 synthesis calls.
_LOOKUP_TIMEOUT_SECONDS = 25.0

_ROLE_REQUIREMENTS_PATH = Path(__file__).resolve().parents[2] / "data" / "role_requirements.json"

_WEB_SEARCH_TOOL: Mapping[str, Any] = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the web for current role/skill requirement info.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
}

_SYSTEM_PROMPT = (
    "You are a labor-market research assistant for Campus IQ. Given a target "
    "job/internship role title, research its real, current skill and "
    "certification requirements using the web_search tool as needed (you may "
    "call it up to 3 times). When you have enough information, respond with "
    "JSON ONLY (no Markdown fences) matching exactly this schema:\n"
    '{"soc_code": "string (2018 SOC/O*NET-SOC code, e.g. 15-1252.00)", '
    '"soc_title": "string", '
    '"must_have_skills": ["string", ...], '
    '"nice_to_have_skills": ["string", ...], '
    '"must_have_certifications": ["string", ...], '
    '"nice_to_have_certifications": ["string", ...]}\n'
    "Use an empty list for any category with nothing to report. Once you are "
    "ready to answer, respond with the JSON object directly instead of "
    "calling another tool."
)

_REQUIRED_KEYS = (
    "soc_code",
    "soc_title",
    "must_have_skills",
    "nice_to_have_skills",
    "must_have_certifications",
    "nice_to_have_certifications",
)

_LIST_KEYS = (
    "must_have_skills",
    "nice_to_have_skills",
    "must_have_certifications",
    "nice_to_have_certifications",
)


def _known_soc_codes() -> frozenset[str]:
    """SOC codes already curated in data/role_requirements.json.

    Used to reject hallucinated soc_code values from the agent. An empty
    result (file missing/unreadable) disables this check rather than
    rejecting every agent response -- see _validate_schema.
    """
    try:
        with _ROLE_REQUIREMENTS_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return frozenset()
    if not isinstance(data, Mapping):
        return frozenset()
    return frozenset(
        entry["soc_code"]
        for key, entry in data.items()
        if not key.startswith("_")
        and isinstance(entry, Mapping)
        and isinstance(entry.get("soc_code"), str)
        and entry["soc_code"]
    )


def _execute_tool_call(name: str, arguments: Mapping[str, Any]) -> str:
    """Execute one tool call and return its string result.

    Stage-1 stub: web_search is not wired to a real provider yet (Stage 2).
    Returns an empty-results marker so the loop's control flow (message
    round-trips, round counting, time budget) is exercised end to end even
    though no real search happens yet.
    """
    if name == "web_search":
        return json.dumps({"results": [], "note": "web_search not yet wired (Stage 2)."})
    return json.dumps({"error": f"Unknown tool '{name}'."})


def _validate_schema(data: Any, known_soc_codes: frozenset[str]) -> dict[str, Any] | None:
    if not isinstance(data, Mapping):
        return None
    if any(key not in data for key in _REQUIRED_KEYS):
        return None

    soc_code = data.get("soc_code")
    soc_title = data.get("soc_title")
    if not isinstance(soc_code, str) or not soc_code.strip():
        return None
    if known_soc_codes and soc_code not in known_soc_codes:
        return None
    if not isinstance(soc_title, str) or not soc_title.strip():
        return None

    validated: dict[str, Any] = {"soc_code": soc_code, "soc_title": soc_title}
    for key in _LIST_KEYS:
        value = data.get(key)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            return None
        validated[key] = value
    return validated


def _run_tool_loop(role: str, client: OpenRouterClient) -> dict[str, Any] | None:
    known_soc_codes = _known_soc_codes()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": f"Target role: {role}"},
    ]

    deadline = time.monotonic() + _TIME_BUDGET_SECONDS

    for round_index in range(_MAX_TOOL_ROUNDS + 1):
        if time.monotonic() >= deadline:
            return None

        message = client.complete_message(
            messages=messages,
            model=_LOOKUP_MODEL,
            extra_body={"tools": [_WEB_SEARCH_TOOL]},
        )
        if not isinstance(message, Mapping):
            return None

        tool_calls = message.get("tool_calls")
        if not tool_calls:
            content = message.get("content")
            if not isinstance(content, str) or not content.strip():
                return None
            try:
                parsed = parse_ai_json_response(content)
            except AIResponseParseError:
                return None
            return _validate_schema(parsed, known_soc_codes)

        if round_index >= _MAX_TOOL_ROUNDS:
            # Model still wants to call tools after using up its budget.
            return None

        messages.append(
            {
                "role": "assistant",
                "content": message.get("content") or "",
                "tool_calls": tool_calls,
            }
        )
        for tool_call in tool_calls:
            function = tool_call.get("function", {}) if isinstance(tool_call, Mapping) else {}
            name = function.get("name", "")
            try:
                arguments = json.loads(function.get("arguments") or "{}")
            except json.JSONDecodeError:
                arguments = {}
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.get("id", ""),
                    "content": _execute_tool_call(name, arguments),
                }
            )

    return None


def get_role_requirements(role: str, client: OpenRouterClient | None = None) -> dict[str, Any] | None:
    """Look up live skill/certification requirements for one target role.

    Never raises -- any failure (timeout, malformed JSON, unknown SOC code,
    request/config error) returns None so callers can fall back to the
    static data/role_requirements.json lookup silently.
    """
    if not isinstance(role, str) or not role.strip():
        return None

    try:
        active_client = client if client is not None else OpenRouterClient(timeout=_LOOKUP_TIMEOUT_SECONDS)
        result = _run_tool_loop(role, active_client)
    except (AIConfigError, AIRequestError, AIResponseParseError, ValueError, TimeoutError) as exc:
        logger.info("role_research source=static_fallback role=%s error=%s", role, exc)
        return None

    if result is None:
        logger.info("role_research source=static_fallback role=%s", role)
        return None

    logger.info("role_research source=agent role=%s", role)
    return result
