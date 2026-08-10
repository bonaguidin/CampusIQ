"""Turn extracted transcript text into validated, storable course rows.

Stage 2 of the transcript parser. Sits between extraction.py (bytes -> text)
and store.py (structure -> rows), and follows the same CareerFeatureRunner
convention resume/parser.py does: a system message demanding JSON-only output,
a user message carrying the prompt template plus the contract, one
client.complete(...) call, then parse_ai_json_response() on the text.

TWO DELIBERATE DIVERGENCES FROM resume/parser.py
------------------------------------------------

1. REJECT, DO NOT REPAIR. resume/parser.py repairs field-by-field: a bad
   certifications.status becomes null, a malformed list becomes [], and the
   row is kept with a warning. That is right for a resume, where a dropped
   field costs a line on a profile page.

   It is wrong here. Every field on a course row feeds arithmetic. A
   credit_hours that silently becomes 0.0, or a letter_grade that silently
   becomes null, does not degrade the record -- it changes the student's GPA
   to a different, plausible, wrong number, with nothing downstream able to
   detect it. So a row missing or failing validation on credit_hours or
   letter_grade is REJECTED into `rejected`, never coerced into `courses`.
   Rejected rows are reported to the caller for human review; they are not
   written.

2. temperature=0 on the model call. A transcript parse is transcription: one
   document, one correct answer. resume/parser.py does not currently pass a
   temperature and is deliberately left alone -- changing a live parser's
   sampling is not this module's business.

WHY letter_grade IS CHECKED AGAINST grade_point_map
---------------------------------------------------
An unmapped letter is the specific failure this module exists to prevent. If
"B+" is stored for a TAMU student, whose map has no B+ row, gpa.py resolves it
as unmapped and drops the course from the GPA -- correctly, per its own rules,
but invisibly: the student sees a GPA computed over fewer courses than they
took, with no error anywhere. Validating against the institution's ACTUAL map
keys at parse time turns that silent drop into a visible review item.

Note this is checked against the raw map keys, NOT through gpa.resolve_grade().
resolve_grade applies plus/minus stripping for institutions with
uses_plus_minus=false, which would let "B+" through for TAMU as a normalized
"B". That is correct behavior for computing a GPA from stored data, but wrong
as a parse-time gate: a B+ printed on a TAMU transcript means the extraction
or the document is anomalous, and a human should see it before it is stored.
"""

import json
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping

from GradusIQ_career.ai.parser import parse_ai_json_response


PROMPT_PATH = Path(__file__).resolve().parents[1] / "gradus_iq_prompt_TRANSCRIPT.md"

ParseStatus = Literal["ok", "not_a_transcript", "unparseable"]
VALID_STATUSES: frozenset[str] = frozenset({"ok", "not_a_transcript", "unparseable"})

# course_records.status carries a live CHECK constraint
# (status in ('completed', 'in_progress')).
VALID_COURSE_STATUSES: frozenset[str] = frozenset({"completed", "in_progress"})

# Caps. A hostile or looping model could otherwise emit thousands of rows for
# one upload. 600 courses is roughly four times a full undergraduate degree,
# so this bounds the damage without rejecting any realistic transcript.
MAX_COURSES = 600
MAX_TERM_SUMMARIES = 60
MAX_FIELD_CHARS = 500

# Guards the prompt against an enormous upload.
#
# UNLIKE resume/parser.py, EXCEEDING THIS IS A HARD ERROR, NOT A TRUNCATION.
# build_messages() raises TranscriptTooLongError rather than slicing. Resume's
# build_messages slices to MAX_PROMPT_CHARS and appends a "[truncated]" note,
# which for a resume costs a trailing bullet. Truncating a transcript instead
# silently deletes the final terms -- the model never sees them, so they are
# absent from `courses` with no warning, and the resulting GPA is computed over
# a subset of the student's coursework. That is indistinguishable from a
# correct parse from the outside. The upload is refused instead.
MAX_PROMPT_CHARS = 60_000

# course_records.credit_hours is numeric(4,2): 0.00 through 99.99.
MIN_CREDIT_HOURS = Decimal("0")
MAX_CREDIT_HOURS = Decimal("99.99")
CREDIT_HOURS_QUANTUM = Decimal("0.01")


OUTPUT_CONTRACT: Mapping[str, Any] = {
    "status": "ok | not_a_transcript | unparseable",
    "courses": [
        {
            "course_code": "string, exactly as printed, e.g. 'MATH 251'",
            "title": "string or null, exactly as printed",
            "credit_hours": "number or null -- attempted hours; null if unreadable, never guessed",
            "letter_grade": "string or null, exactly as printed including +/-; null if none",
            "term_label": "string or null -- the term heading this course appears under",
            "status": "completed | in_progress",
        }
    ],
    "term_summaries": [
        {
            "term_label": "string",
            "term_gpa": "number or null -- only if printed on the transcript",
            "term_credit_hours": "number or null -- only if printed on the transcript",
        }
    ],
}


class TranscriptContractError(ValueError):
    """The model's response cannot be interpreted as a transcript parse.

    Subclasses ValueError so it is caught by the same `except (... ValueError)`
    tuple features/base.py:65 uses, matching ResumeContractError.
    """


class TranscriptTooLongError(ValueError):
    """Extracted text exceeds MAX_PROMPT_CHARS.

    A distinct type because the route turns this into a specific 413 telling
    the student the document is too long, rather than a generic parse failure.
    Subclasses ValueError for the same reason as above.
    """


@dataclass(frozen=True)
class RejectedRow:
    """A course row that failed validation and must not be written.

    Carries the raw entry as the model returned it so a review screen can show
    the student what was on the page, next to the reason it could not be used.
    """

    index: int
    reason: str
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"index": self.index, "reason": self.reason, "raw": self.raw}


@dataclass(frozen=True)
class TermSummary:
    """Term totals as PRINTED on the transcript -- never computed here.

    Used only by the arithmetic cross-check in store.py, which compares these
    against the parsed rows to catch dropped or duplicated courses.
    """

    term_label: str
    term_gpa: float | None = None
    term_credit_hours: float | None = None


@dataclass(frozen=True)
class ParsedTranscript:
    status: ParseStatus
    courses: list[dict[str, Any]] = field(default_factory=list)
    term_summaries: list[TermSummary] = field(default_factory=list)
    # Rows that could not be validated. NOT written; surfaced for review.
    rejected: list[RejectedRow] = field(default_factory=list)
    # Non-fatal notes about the response as a whole (unexpected keys, caps
    # hit). Never used to record a dropped course -- that is `rejected`.
    warnings: list[str] = field(default_factory=list)

    @property
    def has_content(self) -> bool:
        return bool(self.courses)


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


def build_messages(transcript_text: str, prompt_template: str) -> list[dict[str, str]]:
    """Same two-message shape as CareerFeatureRunner.build_messages.

    Raises TranscriptTooLongError instead of truncating -- see MAX_PROMPT_CHARS.
    """
    if len(transcript_text) > MAX_PROMPT_CHARS:
        raise TranscriptTooLongError(
            f"Transcript text is {len(transcript_text):,} characters, over the "
            f"{MAX_PROMPT_CHARS:,}-character limit. Truncating a transcript would "
            "silently drop courses and produce an incorrect GPA, so the upload is "
            "refused instead. Upload a single transcript rather than a combined "
            "document, or split it by institution."
        )

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
                "Transcript text:\n"
                f"{transcript_text}"
            ),
        },
    ]


# -- coercion helpers ---------------------------------------------------------


def _clean_str(value: Any) -> str | None:
    """A trimmed, length-capped string, or None for anything unusable."""
    if not isinstance(value, str):
        return None
    trimmed = value.strip()[:MAX_FIELD_CHARS].strip()
    return trimmed or None


def coerce_credit_hours(value: Any) -> Decimal | None:
    """Coerce to a numeric(4,2)-safe Decimal, or None if it cannot be.

    None means REJECT THE ROW. It never means "use a default" -- there is no
    safe default for a credit-hour value, which is one of the two multiplicands
    in every quality-point calculation.

    Accepts int, float, and numeric strings ("3", "3.0", " 4.00 "). Rejects
    bools (isinstance(True, int) is True in Python, and a True credit_hours is
    a parse failure, not one credit), non-finite floats, negatives, and
    anything over the column's 99.99 ceiling.
    """
    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float, Decimal)):
        try:
            candidate = Decimal(str(value))
        except InvalidOperation:
            return None
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            candidate = Decimal(text)
        except InvalidOperation:
            return None
    else:
        return None

    if not candidate.is_finite():
        return None
    if candidate < MIN_CREDIT_HOURS or candidate > MAX_CREDIT_HOURS:
        return None

    # Quantize to the column's scale. ROUND_HALF_EVEN on the second decimal is
    # not a "repair" of a bad value -- it is representing a good one at the
    # precision the column stores.
    try:
        return candidate.quantize(CREDIT_HOURS_QUANTUM)
    except InvalidOperation:
        return None


def _coerce_optional_float(value: Any) -> float | None:
    """For PRINTED term summary values. Null rather than reject -- these are
    cross-check inputs, not stored data, so an unreadable one costs a check."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        result = float(value)
        return result if result == result and abs(result) != float("inf") else None
    if isinstance(value, str):
        try:
            return float(value.strip())
        except (ValueError, TypeError):
            return None
    return None


def clean_courses(
    raw: Any,
    *,
    grade_letters: Iterable[str],
    warnings: list[str],
) -> tuple[list[dict[str, Any]], list[RejectedRow]]:
    """Split the model's course list into (writable rows, rejected rows).

    `grade_letters` is the institution's actual grade_point_map keys. A
    letter_grade outside that set rejects the row -- see the module docstring.
    """
    known_letters = set(grade_letters)
    accepted: list[dict[str, Any]] = []
    rejected: list[RejectedRow] = []

    if raw is None:
        return accepted, rejected
    if not isinstance(raw, list):
        warnings.append(f"courses: expected a list, got {type(raw).__name__}; ignored")
        return accepted, rejected

    for index, entry in enumerate(raw):
        if len(accepted) + len(rejected) >= MAX_COURSES:
            warnings.append(
                f"courses: truncated at {MAX_COURSES} rows ({len(raw)} returned)"
            )
            break

        if not isinstance(entry, Mapping):
            rejected.append(RejectedRow(index, "not_an_object", {}))
            continue

        snapshot = {k: v for k, v in entry.items() if isinstance(k, str)}

        course_code = _clean_str(entry.get("course_code"))
        if course_code is None:
            rejected.append(RejectedRow(index, "missing_course_code", snapshot))
            continue

        status = entry.get("status")
        status_text = status.strip().lower() if isinstance(status, str) else None
        if status_text not in VALID_COURSE_STATUSES:
            # NOT defaulted to "completed". A course wrongly marked completed
            # enters the official GPA with whatever grade it carries.
            rejected.append(RejectedRow(index, "invalid_status", snapshot))
            continue

        credit_hours = coerce_credit_hours(entry.get("credit_hours"))
        if credit_hours is None:
            rejected.append(RejectedRow(index, "uncoercible_credit_hours", snapshot))
            continue

        letter_grade = _clean_str(entry.get("letter_grade"))
        if letter_grade is None:
            # A null grade is legitimate ONLY for in-progress coursework. A
            # completed course with no grade cannot be scored and must not be
            # silently stored as an unmapped row that vanishes from the GPA.
            if status_text != "in_progress":
                rejected.append(RejectedRow(index, "missing_letter_grade", snapshot))
                continue
        elif letter_grade not in known_letters:
            rejected.append(RejectedRow(index, "unmapped_letter_grade", snapshot))
            continue

        accepted.append(
            {
                "course_code": course_code,
                "title": _clean_str(entry.get("title")),
                "credit_hours": credit_hours,
                "letter_grade": letter_grade,
                "term_label": _clean_str(entry.get("term_label")),
                "status": status_text,
            }
        )

    return accepted, rejected


def clean_term_summaries(raw: Any, warnings: list[str]) -> list[TermSummary]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        warnings.append(
            f"term_summaries: expected a list, got {type(raw).__name__}; ignored"
        )
        return []

    summaries: list[TermSummary] = []
    for entry in raw[:MAX_TERM_SUMMARIES]:
        if not isinstance(entry, Mapping):
            continue
        label = _clean_str(entry.get("term_label"))
        if label is None:
            continue
        summaries.append(
            TermSummary(
                term_label=label,
                term_gpa=_coerce_optional_float(entry.get("term_gpa")),
                term_credit_hours=_coerce_optional_float(entry.get("term_credit_hours")),
            )
        )
    return summaries


def validate_parsed_transcript(
    payload: Mapping[str, Any],
    *,
    grade_letters: Iterable[str],
) -> ParsedTranscript:
    """Coerce a parsed JSON object into a ParsedTranscript, or raise.

    Raises TranscriptContractError only for failures that make the whole
    response meaningless -- a non-object payload, or a missing/unknown
    `status`. Individual bad rows are rejected, not repaired, and not fatal.
    """
    if not isinstance(payload, Mapping):
        raise TranscriptContractError(
            f"Transcript contract violation: expected a JSON object, "
            f"got {type(payload).__name__}."
        )

    raw_status = payload.get("status")
    status = raw_status.strip().lower() if isinstance(raw_status, str) else None
    if status not in VALID_STATUSES:
        raise TranscriptContractError(
            f"Transcript contract violation: 'status' must be one of "
            f"{sorted(VALID_STATUSES)}, got {raw_status!r}."
        )

    warnings: list[str] = []

    if status != "ok":
        # A non-ok status writes nothing, so its payload is not worth
        # validating -- but it must not smuggle content through either.
        return ParsedTranscript(status=status, warnings=warnings)

    courses, rejected = clean_courses(
        payload.get("courses"), grade_letters=grade_letters, warnings=warnings
    )

    unexpected = set(payload) - {"status", "courses", "term_summaries"}
    if unexpected:
        warnings.append(f"ignored unexpected top-level key(s): {sorted(unexpected)}")

    return ParsedTranscript(
        status="ok",
        courses=courses,
        term_summaries=clean_term_summaries(payload.get("term_summaries"), warnings),
        rejected=rejected,
        warnings=warnings,
    )


def parse_transcript_text(
    transcript_text: str,
    ai_client: Any,
    *,
    grade_letters: Iterable[str],
    prompt_path: Path | None = None,
):
    """One model call plus validation. Returns (ParsedTranscript, model_name).

    Raises the same exception family features/base.py catches -- OSError,
    AIConfigError, AIRequestError, AIResponseParseError, ValueError (and so
    TranscriptContractError and TranscriptTooLongError) -- and the caller maps
    them to a structured failure.
    """
    prompt_template = load_prompt_template(prompt_path)
    response = ai_client.complete(
        messages=build_messages(transcript_text, prompt_template),
        role="parsing",
        # Transcription, not generation. See the module docstring.
        temperature=0,
    )
    payload = parse_ai_json_response(response.text)
    parsed = validate_parsed_transcript(payload, grade_letters=grade_letters)
    return parsed, getattr(response, "model", None)
