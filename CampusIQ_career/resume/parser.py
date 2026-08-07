"""Turn extracted resume text into a validated, storable structure.

Stage 2 of the resume parser. Sits between extraction.py (bytes -> text) and
store.py (structure -> rows).

Follows the CareerFeatureRunner convention in features/base.py exactly: a
system message demanding JSON-only output, a user message carrying the prompt
template plus json.dumps(contract, indent=2), one client.complete(...) call,
then parse_ai_json_response() on the text. It is deliberately NOT a
CareerFeatureRunner subclass -- that base class is built around a
student_profile mapping and a required_paths pre-flight check, and a resume
parse has neither. Sharing the convention without inheriting the wrong shape
is the point.

VALIDATION IS NOT OPTIONAL. parse_ai_json_response only guarantees "this was a
JSON object". Everything past that -- field names, types, the certifications
status vocabulary that a live CHECK constraint enforces, the row counts -- is
checked here, because the next thing that happens to this data is an INSERT
into the student's permanent record.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Mapping

from CampusIQ_career.ai.parser import parse_ai_json_response


PROMPT_PATH = Path(__file__).resolve().parents[1] / "campus_iq_prompt_RESUME.md"

ParseStatus = Literal["ok", "not_a_resume", "unparseable"]
VALID_STATUSES: frozenset[str] = frozenset({"ok", "not_a_resume", "unparseable"})

# certifications.status carries a live CHECK constraint
# (certifications_status_check: status is null or in ('completed',
# 'in_progress')). Anything else the model invents is coerced to None rather
# than sent to Postgres to be rejected.
VALID_CERT_STATUSES: frozenset[str] = frozenset({"completed", "in_progress"})

# Caps. A hostile or looping model could otherwise emit thousands of rows for
# one upload; these bound the damage without rejecting any realistic resume.
MAX_ITEMS_PER_TABLE = 100
MAX_LIST_ENTRIES = 100
MAX_FIELD_CHARS = 4000

# Guards the prompt against an enormous upload. Flash-tier has a large context
# window, but there is no reason to pay for a 500-page PDF.
MAX_PROMPT_CHARS = 60_000

PROFILE_LIST_FIELDS = ("target_roles", "interests", "skills_technical", "skills_soft")

# (field name, required key, optional scalar fields, optional list fields)
ITEM_SPECS = {
    "certifications": ("name", ("issuer", "status", "date"), ()),
    "work_experience": ("employer", ("role", "duration", "location", "description"), ("skills_gained",)),
    "projects": ("name", ("timeframe", "description"), ("tools",)),
}

OUTPUT_CONTRACT: Mapping[str, Any] = {
    "status": "ok|not_a_resume|unparseable",
    "profile": {
        "target_roles": ["string"],
        "interests": ["string"],
        "skills_technical": ["string"],
        "skills_soft": ["string"],
    },
    "certifications": [
        {
            "name": "string (required)",
            "issuer": "string|null",
            "status": "completed|in_progress|null",
            "date": "string|null",
        }
    ],
    "work_experience": [
        {
            "employer": "string (required)",
            "role": "string|null",
            "duration": "string|null",
            "location": "string|null",
            "description": "string|null",
            "skills_gained": ["string"],
        }
    ],
    "projects": [
        {
            "name": "string (required)",
            "timeframe": "string|null",
            "description": "string|null",
            "tools": ["string"],
        }
    ],
}


class ResumeContractError(ValueError):
    """The model returned JSON that does not satisfy the resume contract.

    Subclasses ValueError so it is caught by the same `except (... ValueError)`
    tuple features/base.py:65 uses, rather than needing a new branch.
    """


@dataclass(frozen=True)
class ParsedResume:
    status: ParseStatus
    profile: dict[str, list[str]] = field(default_factory=dict)
    certifications: list[dict[str, Any]] = field(default_factory=list)
    work_experience: list[dict[str, Any]] = field(default_factory=list)
    projects: list[dict[str, Any]] = field(default_factory=list)
    # Fields dropped or coerced during validation. Surfaced in the response so
    # a silently-discarded row is visible rather than mysterious.
    warnings: list[str] = field(default_factory=list)

    @property
    def has_content(self) -> bool:
        return bool(
            self.certifications
            or self.work_experience
            or self.projects
            or any(self.profile.values())
        )


def load_prompt_template(path: Path | None = None) -> str:
    """Mirrors features/base.py:load_prompt_template, including its errors."""
    resolved = Path(path) if path else PROMPT_PATH
    try:
        prompt = resolved.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Prompt file not found: {resolved}") from exc
    if not prompt.strip():
        raise ValueError(f"Prompt file is empty: {resolved}")
    return prompt


def build_messages(resume_text: str, prompt_template: str) -> list[dict[str, str]]:
    """Same two-message shape as CareerFeatureRunner.build_messages."""
    truncated = resume_text[:MAX_PROMPT_CHARS]
    if len(resume_text) > MAX_PROMPT_CHARS:
        truncated += "\n\n[resume text truncated at the extraction length limit]"
    return [
        {
            "role": "system",
            "content": (
                "You are Campus IQ. Return valid JSON only. Do not wrap the response "
                "in Markdown. Follow the requested output contract exactly."
            ),
        },
        {
            "role": "user",
            "content": (
                f"{prompt_template}\n\n"
                "Return JSON only using this contract:\n"
                f"{json.dumps(OUTPUT_CONTRACT, indent=2)}\n\n"
                "Resume text:\n"
                f"{truncated}"
            ),
        },
    ]


# ── coercion helpers ─────────────────────────────────────────────────────────


def _clean_str(value: Any) -> str | None:
    """A trimmed, length-capped string, or None for anything unusable."""
    if not isinstance(value, str):
        return None
    trimmed = value.strip()[:MAX_FIELD_CHARS].strip()
    return trimmed or None


def _clean_str_list(value: Any) -> list[str]:
    """A de-duplicated list of clean strings, order preserved.

    Anything that is not a list of strings degrades to [] rather than raising:
    a model returning "Python, SQL" instead of ["Python", "SQL"] should cost
    one field, not the whole upload.
    """
    if isinstance(value, str):
        candidates: list[Any] = [value]
    elif isinstance(value, (list, tuple)):
        candidates = list(value)
    else:
        return []

    seen: set[str] = set()
    cleaned: list[str] = []
    for item in candidates:
        text = _clean_str(item)
        if text is None or text.casefold() in seen:
            continue
        seen.add(text.casefold())
        cleaned.append(text)
        if len(cleaned) >= MAX_LIST_ENTRIES:
            break
    return cleaned


def _clean_items(
    raw: Any, table: str, warnings: list[str]
) -> list[dict[str, Any]]:
    required_key, scalar_fields, list_fields = ITEM_SPECS[table]

    if raw is None:
        return []
    if not isinstance(raw, list):
        warnings.append(f"{table}: expected a list, got {type(raw).__name__}; ignored")
        return []

    items: list[dict[str, Any]] = []
    for index, entry in enumerate(raw):
        if len(items) >= MAX_ITEMS_PER_TABLE:
            warnings.append(
                f"{table}: truncated at {MAX_ITEMS_PER_TABLE} items ({len(raw)} returned)"
            )
            break
        if not isinstance(entry, Mapping):
            warnings.append(f"{table}[{index}]: not an object; dropped")
            continue

        required_value = _clean_str(entry.get(required_key))
        if required_value is None:
            warnings.append(f"{table}[{index}]: missing required '{required_key}'; dropped")
            continue

        item: dict[str, Any] = {required_key: required_value}
        for name in scalar_fields:
            item[name] = _clean_str(entry.get(name))
        for name in list_fields:
            item[name] = _clean_str_list(entry.get(name))

        # Enforce the live CHECK constraint rather than letting Postgres 400.
        if table == "certifications":
            status = item.get("status")
            if status is not None and status.strip().lower() not in VALID_CERT_STATUSES:
                warnings.append(
                    f"certifications[{index}]: status {status!r} outside "
                    "('completed','in_progress'); set to null"
                )
                item["status"] = None
            elif status is not None:
                item["status"] = status.strip().lower()

        items.append(item)

    return items


def validate_parsed_resume(payload: Mapping[str, Any]) -> ParsedResume:
    """Coerce a parsed JSON object into a ParsedResume, or raise.

    Raises ResumeContractError only for failures that make the whole response
    meaningless -- a non-object payload, or a missing/unknown `status`. Every
    other defect is repaired field-by-field and recorded in `warnings`, so one
    malformed work-experience entry does not discard a good resume.
    """
    if not isinstance(payload, Mapping):
        raise ResumeContractError(
            f"Resume contract violation: expected a JSON object, got {type(payload).__name__}."
        )

    raw_status = payload.get("status")
    status = raw_status.strip().lower() if isinstance(raw_status, str) else None
    if status not in VALID_STATUSES:
        raise ResumeContractError(
            f"Resume contract violation: 'status' must be one of "
            f"{sorted(VALID_STATUSES)}, got {raw_status!r}."
        )

    warnings: list[str] = []

    if status != "ok":
        # A non-ok status writes nothing, so its payload is not worth
        # validating -- but it must not smuggle content through either.
        return ParsedResume(status=status, warnings=warnings)

    raw_profile = payload.get("profile")
    if raw_profile is not None and not isinstance(raw_profile, Mapping):
        warnings.append(f"profile: expected an object, got {type(raw_profile).__name__}; ignored")
        raw_profile = None
    profile_source: Mapping[str, Any] = raw_profile or {}
    profile = {name: _clean_str_list(profile_source.get(name)) for name in PROFILE_LIST_FIELDS}

    unexpected = set(payload) - {"status", "profile", *ITEM_SPECS}
    if unexpected:
        warnings.append(f"ignored unexpected top-level key(s): {sorted(unexpected)}")

    return ParsedResume(
        status="ok",
        profile=profile,
        certifications=_clean_items(payload.get("certifications"), "certifications", warnings),
        work_experience=_clean_items(payload.get("work_experience"), "work_experience", warnings),
        projects=_clean_items(payload.get("projects"), "projects", warnings),
        warnings=warnings,
    )


def parse_resume_text(resume_text: str, ai_client: Any, *, prompt_path: Path | None = None):
    """One model call plus validation. Returns (ParsedResume, model_name).

    Raises the same exception family features/base.py catches -- OSError,
    AIConfigError, AIRequestError, AIResponseParseError, ValueError (and so
    ResumeContractError) -- and the caller maps them to a structured failure.
    """
    prompt_template = load_prompt_template(prompt_path)
    response = ai_client.complete(
        messages=build_messages(resume_text, prompt_template),
        role="parsing",
    )
    payload = parse_ai_json_response(response.text)
    return validate_parsed_resume(payload), getattr(response, "model", None)
