"""Read and edit the unconfirmed career rows a resume parse produced.

Stage 3's backend half. Like store.py, every function takes a session-scoped
client built by CampusIQ_career.supabase_client.build_client_for_token, so RLS
narrows every read and write to the caller's own rows. This module never
constructs a client and never reads SUPABASE_SECRET_KEY.

WHY NOT build_profile_from_supabase: profile_builder drops the ENTIRE career
block when career_profiles.confirmed_at is null, which is precisely the state
this endpoint exists to show. Reading through it would return nothing to
review, every time. So the four tables are queried directly here.

WHY EACH CHILD TABLE IS SCOPED BY student_id, NOT BY JOINING THROUGH
career_profile_id: a second upload adds unconfirmed children even after the
first upload's career_profiles row was confirmed. Walking down from an
unconfirmed career_profiles row would miss exactly those rows -- the common
case for a returning student.

ON THE UPDATE DISAMBIGUATION: PostgREST returns an empty list, with no error,
for all three of "no such row", "row belongs to another student" (RLS), and
"row excluded by the confirmed_at filter". Verified live against the database
under a real non-admin session token. A caller therefore cannot tell a
rejected write from a successful no-op, so apply_edit re-reads to decide, and
collapses not-found and not-yours into one NotFound -- distinguishing them
would leak the existence of another student's row.
"""

from typing import Any, Mapping

from .store import _now_iso, _rows


# URL segment -> real table name. An explicit mapping rather than accepting a
# table name from the path, matching the style of api.py's _ME_FEATURE_NAMES
# and DEMO_STUDENT_SLUGS: the set of reachable tables is closed and lives in
# code, so no request can name a table this module did not choose to expose.
TABLE_BY_SEGMENT: Mapping[str, str] = {
    "career_profile": "career_profiles",
    "certifications": "certifications",
    "work_experience": "work_experience",
    "projects": "projects",
}

# Student-editable content columns, verified against the live schema rather
# than migration files. Everything absent here is system-managed: id,
# student_id, career_profile_id, source, confirmed_at, created_at, updated_at.
# confirmed_at in particular is writable ONLY by the confirm endpoint.
EDITABLE_FIELDS: Mapping[str, tuple[str, ...]] = {
    "career_profiles": (
        "target_roles",
        "interests",
        "career_goals",
        "geographic_preference",
        "ai_anxiety_level",
        "skills_technical",
        "skills_soft",
        "ai_exposure",
    ),
    "certifications": ("name", "issuer", "status", "date"),
    "work_experience": ("employer", "role", "duration", "location", "description", "skills_gained"),
    "projects": ("name", "timeframe", "description", "tools"),
}

# Columns backing each table's live natural-key unique index. Used only to name
# the colliding field in a 23505 message.
NATURAL_KEY_COLUMNS: Mapping[str, tuple[str, ...]] = {
    "certifications": ("name",),
    "work_experience": ("employer", "role"),
    "projects": ("name",),
}

# certifications.status carries a live CHECK constraint
# (certifications_status_check). Validated here so a bad value is a clean 422
# rather than an opaque Postgres error surfacing as a 500.
VALID_CERT_STATUSES = frozenset({"completed", "in_progress"})

# Columns that must never be writable through the edit endpoint, listed
# explicitly so the reason is greppable rather than implied by absence.
SYSTEM_MANAGED_FIELDS = frozenset(
    {"id", "student_id", "career_profile_id", "source", "confirmed_at", "created_at", "updated_at"}
)

UNIQUE_VIOLATION = "23505"

# The response key each table is reported under.
RESPONSE_KEY = {
    "career_profiles": "career_profile",
    "certifications": "certifications",
    "work_experience": "work_experience",
    "projects": "projects",
}


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


def project_row(table: str, row: Mapping[str, Any]) -> dict[str, Any]:
    """Reduce a raw row to id + editable content + source.

    Projection happens in Python rather than through a PostgREST column list
    so the response shape is guaranteed by this function alone: a change to the
    query, or a column added to the table later, cannot leak student_id or any
    other system column into the payload.
    """
    projected: dict[str, Any] = {"id": row.get("id")}
    for column in EDITABLE_FIELDS[table]:
        projected[column] = row.get(column)
    projected["source"] = row.get("source")
    return projected


def load_unconfirmed(client: Any, student_id: str) -> dict[str, Any]:
    """Every unconfirmed row for this student, grouped by table.

    career_profiles yields at most one row (student_id is UNIQUE) and is
    reported as an object or null; the three child tables are always lists,
    empty rather than absent when nothing is pending.
    """
    result: dict[str, Any] = {}

    for table in ("career_profiles", "certifications", "work_experience", "projects"):
        rows = _rows(
            client.table(table)
            .select("*")
            .eq("student_id", student_id)
            .is_("confirmed_at", "null")
            .execute()
        )
        projected = [project_row(table, row) for row in rows]
        if table == "career_profiles":
            result[RESPONSE_KEY[table]] = projected[0] if projected else None
        else:
            result[RESPONSE_KEY[table]] = projected

    return result


def clean_edit_fields(table: str, body: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only this table's editable columns; validate the ones that need it.

    Unknown and system-managed keys are dropped SILENTLY rather than rejected.
    A review screen may reasonably echo back a whole row it just read, and
    failing that request would be unhelpful -- what matters is that the
    system-managed values it echoes are never applied.
    """
    if not isinstance(body, Mapping):
        raise ReviewFieldError("Request body must be a JSON object.")

    allowed = EDITABLE_FIELDS[table]
    fields = {key: value for key, value in body.items() if key in allowed}

    if not fields:
        raise ReviewFieldError(
            f"No editable fields supplied for '{table}'. Editable: {', '.join(allowed)}."
        )

    if table == "certifications" and "status" in fields:
        status = fields["status"]
        if status is not None:
            if not isinstance(status, str) or status.strip().lower() not in VALID_CERT_STATUSES:
                raise ReviewFieldError(
                    f"certifications.status must be null, 'completed', or 'in_progress'; "
                    f"got {status!r}."
                )
            fields["status"] = status.strip().lower()

    return fields


def apply_edit(
    client: Any, table: str, row_id: str, student_id: str, body: Mapping[str, Any]
) -> dict[str, Any]:
    """Update one unconfirmed row and return its projected form.

    Raises ReviewFieldError, ReviewRowNotFound, ReviewRowAlreadyConfirmed, or
    ReviewConflict; the route maps each to a status code.
    """
    fields = clean_edit_fields(table, body)
    payload = dict(fields)
    # No trigger maintains updated_at anywhere in this schema (see migration
    # 20260801190523) -- the writing application does, as store.py also does.
    payload["updated_at"] = _now_iso()

    try:
        updated = _rows(
            client.table(table)
            .update(payload)
            .eq("id", row_id)
            .eq("student_id", student_id)
            .is_("confirmed_at", "null")
            .execute()
        )
    except Exception as exc:  # noqa: BLE001 -- inspected and re-raised below
        if getattr(exc, "code", None) == UNIQUE_VIOLATION:
            columns = NATURAL_KEY_COLUMNS.get(table, ())
            raise ReviewConflict(
                f"Another {table} record already uses that "
                f"{' + '.join(columns) or 'value'}. Choose a different value."
            ) from exc
        raise

    if updated:
        return project_row(table, updated[0])

    # Empty result: rejected, or a no-op. Re-read WITHOUT the confirmed_at
    # filter to tell which. RLS keeps this from seeing another student's row.
    existing = _rows(
        client.table(table)
        .select("*")
        .eq("id", row_id)
        .eq("student_id", student_id)
        .execute()
    )
    if not existing:
        raise ReviewRowNotFound(f"No editable {table} record with that id.")

    raise ReviewRowAlreadyConfirmed(
        "This record has already been confirmed and can no longer be edited."
    )
