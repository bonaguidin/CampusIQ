"""Live role-requirements lookup agent (web_search tool loop).

The tool-calling control loop and output validation are exercised against an
injected client (mirroring the ``client=`` mock-injection style used in
``tests/test_career_features.py``). ``web_search`` is wired to Tavily. Wired
into ``GapRunner.role_requirements_for()``.

On the final round, the ``tools`` param is withheld so the model can't just
keep asking for more searches indefinitely -- it must synthesize a final
answer from what it already has.

This module never raises: any failure (timeout, malformed JSON, malformed SOC
code, request/config error) returns ``None`` so ``gap.py`` can fall back to
the static ``data/role_requirements.json`` lookup silently. The module's one
log line records which path (``cache`` / ``agent`` / ``static_fallback``)
served a given lookup, so fallback frequency is visible during demo testing.

A validated agent result carries a ``soc_source`` field: ``"agent"`` (accepted
on format alone) or ``"agent_onet_corroborated"`` (its SOC code also appears
in the small real-O*NET catalog at data/reference/onet_soc_requirements.json
-- positive corroboration only, never used to reject).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Mapping

from tavily import TavilyClient

from GradusIQ_career.ai import AIConfigError, AIRequestError, AIResponseParseError, OpenRouterClient
from GradusIQ_career.ai.parser import parse_ai_json_response

logger = logging.getLogger(__name__)

# Which AgentRole (model_config.py's MODEL_BY_ROLE / ENV_BY_ROLE) drives the
# lookup loop's model selection -- resolves to OPENROUTER_DEEPSEEK_V4_FLASH by
# default, overridable via GRADUSIQ_MODEL_ROLE_RESEARCH like every other role.
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

# Genuinely O*NET-sourced (O*NET 30.3, O*NET-SOC 2019), but only 10
# occupations -- far too narrow to use for rejection. Used solely as a soft
# corroboration signal on soc_source; see _validate_schema.
_ONET_CATALOG_PATH = Path(__file__).resolve().parents[2] / "data" / "reference" / "onet_soc_requirements.json"
_CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / ".cache" / "role_research_cache.json"

_SOC_CODE_PATTERN = re.compile(r"^\d{2}-\d{4}\.\d{2}$")

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
    "You are a labor-market research assistant for Gradus IQ. Given a target "
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
    "These target roles are always entry-level internship, student, or "
    "volunteer positions -- never career-stage placements. Choose the SOC "
    "code for the entry-level individual-contributor occupation the intern "
    "would be training toward, not a management, supervisory, or "
    "director-tier occupation. If your best match is a manager/supervisor "
    "occupation (e.g. an 11-xxxx code, or any title containing "
    '"Managers", "Supervisors", or "Directors"), pick the corresponding '
    "specialist, analyst, technician, or associate occupation instead.\n"
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

# Bounds on the free-text surface of a validated entry.
#
# Everything in _LIST_KEYS (plus soc_title) originates as model output
# synthesized from third-party web-search results, and reaches the GAP prompt
# verbatim via gap.py's _merge_requirements -> build_student_context. Shape
# checks alone let a poisoned search result put arbitrarily long, arbitrarily
# many instruction-shaped strings into that prompt. These two caps bound both
# expressions of that surface: per-item length and item count.
#
# soc_code is deliberately NOT bounded here -- _SOC_CODE_PATTERN already pins
# it to exactly 10 characters, which is far tighter than any length cap.
#
# Sized against the real cache (14 entries, 2026-07): longest element 71 chars,
# longest list 15 items, longest soc_title 58 chars. Both caps clear current
# legitimate content with room to spare, so tightening does not evict working
# entries and force needless re-research.
_MAX_FIELD_CHARS = 120
_MAX_LIST_ITEMS = 20

# The only two values _run_tool_loop ever assigns to soc_source. Kept in sync
# with that assignment; if a third provenance tag is ever introduced, add it
# here or every entry carrying it will fail validation and re-research.
_VALID_SOC_SOURCES = frozenset({"agent", "agent_onet_corroborated"})


def _onet_corroborated_codes() -> frozenset[str]:
    """SOC codes present in the small genuinely-O*NET-sourced catalog.

    Positive-only corroboration signal for soc_source -- an empty result
    (file missing/unreadable) just means nothing gets corroborated, not that
    everything is rejected. The catalog is far too narrow (10 occupations)
    to use as a gate; most legitimate SOC codes simply won't be in it.
    """
    try:
        with _ONET_CATALOG_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return frozenset()
    roles = data.get("roles") if isinstance(data, Mapping) else None
    if not isinstance(roles, Mapping):
        return frozenset()
    return frozenset(code for code in roles if isinstance(code, str))


def _tavily_client() -> TavilyClient | None:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key or not api_key.strip():
        # Distinct from a Tavily request failure (which logs per-call inside
        # _run_web_search's except clause) -- a missing key is a config
        # problem, not "the web had nothing," and would otherwise look
        # identical to any other cause of static_fallback in the logs.
        logger.warning("TAVILY_API_KEY not set, skipping web_search")
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


def _validate_schema(data: Any) -> dict[str, Any] | None:
    """Validate shape, soc_code *format*, and free-text bounds -- not
    membership in any curated allowlist. A well-formed but previously-unseen
    SOC code (the agent doing real, correct research beyond the static file's
    14 hand-picked roles) must be accepted, not discarded to static fallback.
    See soc_source (added by callers) for how much to trust a given code.

    Free-text fields are additionally bounded: every string is capped at
    _MAX_FIELD_CHARS and every list at _MAX_LIST_ITEMS. Oversized content is
    REJECTED, never truncated -- a partial skill name is worse than no entry,
    and truncation would silently admit the first 120 characters of an
    injection payload.

    This runs on both paths, so the bounds apply identically to freshly
    researched content (_run_tool_loop, before caching) and to entries already
    on disk (_read_cache). A pre-existing entry that violates the new bounds
    simply fails here and is treated as a cache miss, matching the module's
    existing fail-safe behavior -- never an exception.
    """
    if not isinstance(data, Mapping):
        return None
    if any(key not in data for key in _REQUIRED_KEYS):
        return None

    soc_code = data.get("soc_code")
    soc_title = data.get("soc_title")
    # soc_code is length-checked by _SOC_CODE_PATTERN, not _MAX_FIELD_CHARS.
    if not isinstance(soc_code, str) or not _SOC_CODE_PATTERN.match(soc_code.strip()):
        return None
    if not isinstance(soc_title, str) or not soc_title.strip():
        return None
    if len(soc_title) > _MAX_FIELD_CHARS:
        return None

    validated: dict[str, Any] = {"soc_code": soc_code, "soc_title": soc_title}
    for key in _LIST_KEYS:
        value = data.get(key)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            return None
        if len(value) > _MAX_LIST_ITEMS:
            return None
        # One oversized element rejects the whole entry, not just that item:
        # dropping items would hand the caller a silently incomplete list.
        if any(len(item) > _MAX_FIELD_CHARS for item in value):
            return None
        validated[key] = value
    # soc_source is OPTIONAL-but-constrained. Absent is valid: freshly parsed
    # agent JSON never carries it, and _run_tool_loop assigns it immediately
    # after this function returns. Present means it must be one of the two
    # values that write path ever assigns -- this is a machine-set provenance
    # tag, not free text, so anything else indicates a hand-edited or corrupted
    # cache entry and fails the whole entry.
    #
    # The isinstance guard is load-bearing, not redundant: a JSON-decoded
    # cache value can be an unhashable list/dict, and `x in <set>` raises
    # TypeError on those. _read_cache is called outside get_role_requirements'
    # try/except, so a raised TypeError would escape into gap.py rather than
    # degrading to a cache miss.
    if "soc_source" in data:
        soc_source = data["soc_source"]
        if not isinstance(soc_source, str) or soc_source not in _VALID_SOC_SOURCES:
            return None
        validated["soc_source"] = soc_source
    return validated


def _run_tool_loop(role: str, client: OpenRouterClient) -> dict[str, Any] | None:
    onet_codes = _onet_corroborated_codes()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": f"Target role: {role}"},
    ]

    deadline = time.monotonic() + _TIME_BUDGET_SECONDS

    for round_index in range(_MAX_TOOL_ROUNDS + 1):
        if time.monotonic() >= deadline:
            return None

        is_final_round = round_index >= _MAX_TOOL_ROUNDS
        if is_final_round:
            # The model has used its full search budget. Withhold the tools
            # param entirely (rather than just hoping the model stops asking)
            # so it is structurally unable to request another round, and
            # nudge it to answer from what it already has instead of just
            # silently truncating the conversation.
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "You have used all available searches. Respond now "
                        "with the final JSON object only, using the "
                        "information you already have."
                    ),
                }
            )

        message = client.complete_message(
            messages=messages,
            role=_LOOKUP_ROLE,
            extra_body=None if is_final_round else {"tools": [_WEB_SEARCH_TOOL]},
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
            validated = _validate_schema(parsed)
            if validated is not None:
                validated["soc_source"] = (
                    "agent_onet_corroborated" if validated["soc_code"] in onet_codes else "agent"
                )
            return validated

        if is_final_round:
            # No tools were offered this round, so any tool_calls here are
            # not actionable -- treat as a failed final answer.
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
    return _validate_schema(entry)


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
