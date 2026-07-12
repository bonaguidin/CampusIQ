"""Parsing helpers for AI-generated JSON."""

import json
import re
from typing import Any

from .errors import AIResponseParseError


FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)


def _loads_object(candidate: str) -> dict[str, Any]:
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise AIResponseParseError(f"Malformed AI JSON response: {exc}") from exc

    if not isinstance(parsed, dict):
        raise AIResponseParseError("AI JSON response must be an object.")
    return parsed


def _extract_balanced_object(text: str) -> str:
    start = text.find("{")
    if start == -1:
        raise AIResponseParseError("AI response does not contain a JSON object.")

    depth = 0
    in_string = False
    escaped = False

    for index in range(start, len(text)):
        char = text[index]

        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue

        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]

    raise AIResponseParseError("AI response contains an incomplete JSON object.")


def extract_json_object(text: str) -> dict[str, Any]:
    if not isinstance(text, str) or not text.strip():
        raise AIResponseParseError("AI response text is empty.")

    stripped = text.strip()
    fenced_matches = FENCED_JSON_RE.findall(stripped)
    candidates = fenced_matches or [stripped]

    last_error: AIResponseParseError | None = None
    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate:
            continue
        try:
            return _loads_object(candidate)
        except AIResponseParseError as exc:
            last_error = exc
            if "{" in candidate:
                try:
                    return _loads_object(_extract_balanced_object(candidate))
                except AIResponseParseError as nested_exc:
                    last_error = nested_exc

    if last_error:
        raise last_error
    raise AIResponseParseError("AI response does not contain a JSON object.")


def parse_ai_json_response(text: str) -> dict[str, Any]:
    return extract_json_object(text)
