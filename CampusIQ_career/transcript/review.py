"""Read and edit the unconfirmed course_records a transcript parse produced.

Structurally the same machinery as resume/review.py -- EDITABLE_FIELDS,
project_row, clean_edit_fields, apply_edit, and the same four error types the
route maps onto status codes. The shapes are reused rather than reinvented;
what differs is the field set and the validation, because course_records
carries CHECK constraints and arithmetic that the career tables do not.

WHY THIS IS A SEPARATE MODULE AND NOT AN ENTRY IN resume/review.py's TABLES
--------------------------------------------------------------------------
resume/review.py's EDITABLE_FIELDS and TABLE_BY_SEGMENT are keyed by career
table names, and its load_unconfirmed() queries exactly those four tables and
returns them under career response keys. Adding course_records to those maps
would put course rows into the career review payload, which the career review
screen would then render. The two review surfaces are separate screens over
separate data; sharing the *pattern* is the reuse that was worth having.

THE "PENDING REVIEW" STATE IS DERIVED, NOT STORED
-------------------------------------------------
"Parsed, unmatched, still pending" is expressible from columns that already
exist:

    source = 'transcript_parse' AND catalog_course_id IS NULL
                                AND confirmed_at IS NULL

so no needs_review column is added. A stored flag would be a second source of
truth that can disagree with the columns it summarizes -- e.g. left true after
a student edits a course_code into one the catalog does match.
"""

from decimal import Decimal
from typing import Any, Mapping

from .parser import VALID_COURSE_STATUSES, coerce_credit_hours
from .store_helpers import now_iso, rows_of


TABLE = "course_records"

# Student-editable content columns. Everything absent here is system-managed.
#
# Four exclusions worth stating explicitly, since their absence is load-bearing
# rather than incidental:
#   counts_toward_credit / counts_toward_gpa -- derived from letter_grade and
#     status via store.counts_flags, and informational only (see that
#     function's docstring). Editable, they would drift from the grade they
#     describe and mislead the very screen they exist to serve. They are
#     recomputed here whenever letter_grade or status changes.
#   catalog_course_id -- set by catalog matching, not by hand. A student
#     pointing a row at an arbitrary catalog course would attach wrong metadata
#     to their record.
#   confirmed_at -- writable ONLY by the confirm endpoint, which is where the
#     grade-scale gate lives. Editable here, it would route around that gate
#     entirely.
EDITABLE_FIELDS: tuple[str, ...] = (
    "course_code",
    "title",
    "credit_hours",
    "letter_grade",
    "status",
)

# Reported alongside the editable fields so a review screen can show why a row
# is flagged, without a second query.
CONTEXT_FIELDS: tuple[str, ...] = (
    "term_id",
    "catalog_course_id",
    "counts_toward_credit",
    "counts_toward_gpa",
    "credit_type",
    "source",
)

SYSTEM_MANAGED_FIELDS = frozenset(
    {
        "id",
        "student_id",
        "institution_id",
        "term_id",
        "catalog_course_id",
        "counts_toward_credit",
        "counts_toward_gpa",
        "credit_type",
        "source",
        "confirmed_at",
        "excluded_from_gpa_by",
        "created_at",
        "updated_at",
    }
)

NATURAL_KEY_COLUMNS = ("term_id", "course_code")

UNIQUE_VIOLATION = "23505"


class ReviewError(Exception):
    """Base for errors the route maps onto a specific HTTP status."""


class ReviewRowNotFound(ReviewError):
    """No such row for this caller. Covers 'absent' and 'someone else's'."""


class ReviewRowAlreadyConfirmed(ReviewError):
    """The row exists and belongs to the caller, but is no longer editable."""


class ReviewFieldError(ReviewError):
    """The request body is unusable -- empty after stripping, or a bad value."""


class ReviewConflict(ReviewError):
    """The edit collides with an existing row's natural key."""


def project_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Reduce a raw row to id + editable content + context.

    Projection happens in Python rather than through a PostgREST column list so
    the response shape is guaranteed by this function alone: a change to the
    query, or a column added to the table later, cannot leak student_id into
    the payload.
    """
    projected: dict[str, Any] = {"id": row.get("id")}
    for column in EDITABLE_FIELDS:
        projected[column] = row.get(column)
    for column in CONTEXT_FIELDS:
        projected[column] = row.get(column)
    projected["needs_catalog_review"] = (
        row.get("source") == "transcript_parse" and row.get("catalog_course_id") is None
    )
    return projected


def load_unconfirmed(client: Any, student_id: str) -> dict[str, Any]:
    """Every unconfirmed course record for this student.

    Scoped by student_id rather than by walking down from a term, so a second
    upload's rows are visible even when the first upload's terms were already
    confirmed.
    """
    rows = rows_of(
        client.table(TABLE)
        .select("*")
        .eq("student_id", student_id)
        .is_("confirmed_at", "null")
        .execute()
    )
    projected = [project_row(row) for row in rows]
    return {
        "course_records": projected,
        "pending_catalog_review": sum(
            1 for row in projected if row["needs_catalog_review"]
        ),
    }


def clean_edit_fields(body: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only editable columns; validate the ones that need it.

    Unknown and system-managed keys are dropped SILENTLY rather than rejected,
    matching resume/review.py: a review screen may echo back a whole row it
    just read, and failing that request would be unhelpful -- what matters is
    that the system-managed values it echoes are never applied.

    credit_hours is the exception to "reject nothing": it goes through the same
    coerce_credit_hours the parser uses, and a value that will not coerce is a
    422 rather than a silent drop. Dropping it would leave the student looking
    at a screen showing the old value with no indication their edit did
    nothing -- and this is the field that multiplies into every quality point.
    """
    if not isinstance(body, Mapping):
        raise ReviewFieldError("Request body must be a JSON object.")

    fields = {key: value for key, value in body.items() if key in EDITABLE_FIELDS}

    if not fields:
        raise ReviewFieldError(
            f"No editable fields supplied. Editable: {', '.join(EDITABLE_FIELDS)}."
        )

    if "course_code" in fields:
        code = fields["course_code"]
        if not isinstance(code, str) or not code.strip():
            raise ReviewFieldError("course_code must be a non-empty string.")
        fields["course_code"] = code.strip()

    if "title" in fields:
        title = fields["title"]
        if title is not None:
            if not isinstance(title, str):
                raise ReviewFieldError("title must be a string or null.")
            fields["title"] = title.strip() or None

    if "credit_hours" in fields:
        coerced = coerce_credit_hours(fields["credit_hours"])
        if coerced is None:
            raise ReviewFieldError(
                f"credit_hours must be a number between 0 and 99.99; "
                f"got {fields['credit_hours']!r}."
            )
        fields["credit_hours"] = str(coerced)

    if "status" in fields:
        status = fields["status"]
        if not isinstance(status, str) or status.strip().lower() not in VALID_COURSE_STATUSES:
            raise ReviewFieldError(
                f"status must be 'completed' or 'in_progress'; got {status!r}."
            )
        fields["status"] = status.strip().lower()

    if "letter_grade" in fields:
        letter = fields["letter_grade"]
        if letter is not None:
            if not isinstance(letter, str) or not letter.strip():
                raise ReviewFieldError("letter_grade must be a non-empty string or null.")
            # NOT validated against grade_point_map here. A student correcting a
            # misread grade should not be blocked by this endpoint's view of the
            # scale; an unmapped letter surfaces as a course excluded from the
            # GPA, with a reason, via gpa.py. Rejecting it here would make an
            # unusual-but-real grade uncorrectable.
            fields["letter_grade"] = letter.strip()

    return fields


def apply_edit(
    client: Any,
    row_id: str,
    student_id: str,
    body: Mapping[str, Any],
    *,
    grade_map: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Update one unconfirmed course record and return its projected form.

    Raises ReviewFieldError, ReviewRowNotFound, ReviewRowAlreadyConfirmed, or
    ReviewConflict; the route maps each to a status code.
    """
    from .store import counts_flags  # local import: store imports parser, not review

    fields = clean_edit_fields(body)
    payload = dict(fields)
    payload["updated_at"] = now_iso()

    # counts_* are derived, never client-supplied. Recomputed whenever the two
    # inputs they depend on change, so they cannot drift from the grade they
    # describe. Needs the row's current values for whichever input was not
    # edited, so this is a read before the write.
    if "letter_grade" in fields or "status" in fields:
        current = rows_of(
            client.table(TABLE)
            .select("*")
            .eq("id", row_id)
            .eq("student_id", student_id)
            .execute()
        )
        if not current:
            raise ReviewRowNotFound("No editable course record with that id.")
        row = current[0]
        letter = fields.get("letter_grade", row.get("letter_grade"))
        status = fields.get("status", row.get("status"))
        resolved_map = grade_map
        if resolved_map is None:
            from .store import grade_map_for

            resolved_map = grade_map_for(client, row.get("institution_id"))
        counts_credit, counts_gpa = counts_flags(letter, str(status), resolved_map)
        payload["counts_toward_credit"] = counts_credit
        payload["counts_toward_gpa"] = counts_gpa

    try:
        updated = rows_of(
            client.table(TABLE)
            .update(payload)
            .eq("id", row_id)
            .eq("student_id", student_id)
            .is_("confirmed_at", "null")
            .execute()
        )
    except Exception as exc:  # noqa: BLE001 -- inspected and re-raised below
        if getattr(exc, "code", None) == UNIQUE_VIOLATION:
            raise ReviewConflict(
                "Another course record already uses that "
                f"{' + '.join(NATURAL_KEY_COLUMNS)}. Choose a different value."
            ) from exc
        raise

    if updated:
        return project_row(updated[0])

    # Empty result: rejected, or a no-op. Re-read WITHOUT the confirmed_at
    # filter to tell which. RLS keeps this from seeing another student's row.
    existing = rows_of(
        client.table(TABLE)
        .select("*")
        .eq("id", row_id)
        .eq("student_id", student_id)
        .execute()
    )
    if not existing:
        raise ReviewRowNotFound("No editable course record with that id.")

    raise ReviewRowAlreadyConfirmed(
        "This record has already been confirmed and can no longer be edited."
    )
