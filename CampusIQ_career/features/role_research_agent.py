"""Live role-requirements lookup agent (web_search tool loop).

The tool-calling control loop and output validation are exercised against an
injected client (mirroring the ``client=`` mock-injection style used in
``tests/test_career_features.py``). ``web_search`` is wired to Tavily.
Wiring this into ``GapRunner.role_requirements_for()`` lands in Stage 3.

This module never raises: any failure (timeout, malformed JSON, unknown SOC
code, request/config error) returns ``None`` so ``gap.py`` can fall back to
the static ``data/role_requirements.json`` lookup silently. The module's one
log line records which path (``cache`` / ``agent`` / ``static_fallback``)
served a given lookup, so fallback frequency is visible during demo testing.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Mapping

from tavily import TavilyClient

from CampusIQ_career.ai import AIConfigError, AIRequestError, AIResponseParseError, OpenRouterClient
from CampusIQ_career.ai.parser import parse_ai_json_response

logger = logging.getLogger(__name__)

# Which AgentRole (model_config.py's MODEL_BY_ROLE / ENV_BY_ROLE) drives the
# lookup loop's model selection -- resolves to OPENROUTER_DEEPSEEK_V4_FLASH by
# default, overridable via CAMPUSIQ_MODEL_ROLE_RESEARCH like every other role.
_LOOKUP_ROLE = "role_research"

# Max number of tool-call round-trips before the loop aborts.
_MAX_TOOL_ROUNDS = 3
# Wall-clock budget for the whole research phase, checked between rounds.
_TIME_BUDGET_SECONDS = 90.0
# Per-call timeout for the Flash-tier lookup model -- explicitly NOT the 300s
# override api.py uses for DeepSeek R1 synthesis calls.
_LOOKUP_TIMEOUT_SECONDS = 25.0
# Tavily's own per-call timeout, kept well under _LOOKUP_TIMEOUT_SECONDS so a
# slow search doesn't eat the whole per-round model-call budget.
_TAVILY_TIMEOUT_SECONDS = 15.0

_ROLE_REQUIREMENTS_PATH = Path(__file__).resolve().parents[2] / "data" / "role_requirements.json"
_CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / ".cache" / "role_research_cache.json"

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


def _tavily_client() -> TavilyClient | None:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key or not api_key.strip():
        return None
    return TavilyClient(api_key=api_key.strip())


def _run_web_search(arguments: Mapping[str, Any]) -> str:
    query = arguments.get("query") if isinstance(arguments, Mapping) else None
    if not isinstance(query, str) or not query.strip():
        return json.dumps({"results": [], "error": "web_search called without a query."})

    client = _tavily_client()
    if client is None:
        return json.dumps({"results": [], "error": "TAVILY_API_KEY is not configured."})

    try:
        response = client.search(query, max_results=5, timeout=_TAVILY_TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 -- Tavily's SDK raises several
        # distinct exception types (auth, usage-limit, timeout, plus whatever
        # the underlying requests call raises). A failed search is a failed
        # tool call, not a fatal error for the whole lookup: the loop just
        # sees empty results and can retry a different query or give up, the
        # same as if the web genuinely had nothing relevant.
        return json.dumps({"results": [], "error": str(exc)})

    results = response.get("results", []) if isinstance(response, Mapping) else []
    summarized = [
        {"title": item.get("title"), "url": item.get("url"), "content": item.get("content")}
        for item in results
        if isinstance(item, Mapping)
    ]
    return json.dumps({"results": summarized})


def _execute_tool_call(name: str, arguments: Mapping[str, Any]) -> str:
    """Execute one tool call and return its string result."""
    if name == "web_search":
        return _run_web_search(arguments)
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
            role=_LOOKUP_ROLE,
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


def _load_cache() -> dict[str, Any]:
    try:
        with _CACHE_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_cache(role: str) -> dict[str, Any] | None:
    entry = _load_cache().get(role)
    # Re-validate on read (not just at write time): a stale cache entry from
    # a prior schema version, or a hand-edited file, must be treated as a
    # miss rather than returned as trusted data.
    return _validate_schema(entry, _known_soc_codes())


def _write_cache(role: str, requirements: dict[str, Any]) -> None:
    cache = _load_cache()
    cache[role] = requirements
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _CACHE_PATH.open("w", encoding="utf-8") as handle:
            json.dump(cache, handle, indent=2, sort_keys=True)
    except OSError:
        # A cache write failure must never break a lookup that already
        # succeeded -- the result is still returned, just not persisted.
        pass


def get_role_requirements(role: str, client: OpenRouterClient | None = None) -> dict[str, Any] | None:
    """Look up live skill/certification requirements for one target role.

    Never raises -- any failure (timeout, malformed JSON, unknown SOC code,
    request/config error) returns None so callers can fall back to the
    static data/role_requirements.json lookup silently.
    """
    if not isinstance(role, str) or not role.strip():
        return None

    cached = _read_cache(role)
    if cached is not None:
        logger.info("role_research source=cache role=%s", role)
        return cached

    try:
        active_client = client if client is not None else OpenRouterClient(timeout=_LOOKUP_TIMEOUT_SECONDS)
        result = _run_tool_loop(role, active_client)
    except (AIConfigError, AIRequestError, AIResponseParseError, ValueError, TimeoutError) as exc:
        logger.info("role_research source=static_fallback role=%s error=%s", role, exc)
        return None

    if result is None:
        logger.info("role_research source=static_fallback role=%s", role)
        return None

    _write_cache(role, result)
    logger.info("role_research source=agent role=%s", role)
    return result
