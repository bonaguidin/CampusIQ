"""The single source of truth for a course's PLANNED -> IN_PROGRESS ->
COMPLETED lifecycle (with an explicit 'dropped' exit).

Nothing in this module invents a parallel status system. It reads/writes the
two tables that already exist -- planned_courses (a future intent, no status
column: its existence in that table IS "planned") and course_records (which
already carries status in ('completed', 'in_progress', 'dropped') as of
20260817220000). This module is what moves a row from the first table into
the second, and what moves a row within the second from in_progress to
completed.

WHY RECONCILIATION RUNS ON READ, NOT ON A TIMER
------------------------------------------------
There is no cron/worker infrastructure in this repo (single uvicorn worker,
no Supabase Edge Functions, no pg_cron -- see the Procfile comment on why
process-local state rules out more than one worker). The safest existing
application point is therefore the same one repeats.reconcile_repeats already
uses: a request handler, run defensively (never fatal) before the response it
would affect is built. promote_due_planned_courses is called from the three
routes whose payload it can change: GET /me/terms, GET /me/planned-courses,
and GET /me/profile (via build_student_intelligence_profile's caller in
api.py). It is cheap (two small reads per call, an upsert per row actually
due) and idempotent, so calling it on every relevant read costs nothing when
there is nothing to promote -- which is true almost every request.

ACTIVATION RULE
----------------
activation_date = term.start_date - 30 days. today >= activation_date means
the term counts as "approaching/active" and any planned course for it belongs
in course_records as in_progress, not in planned_courses. This is a property
of the term, not of a hard-coded month -- Spring, Fall and Summer terms all
promote off their own start_date, read from academic_term_dates.

A term with no calendar row (no academic_term_dates match) can never
activate: there is no start_date to compare against, so the course stays
planned indefinitely rather than promoting on a guess. This mirrors
term_view.py's identical rule for `is_upcoming`.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Mapping

from ..transcript.store import counts_flags, grade_map_for
from ..transcript.store_helpers import now_iso, rows_of
from .planned import clean_course_code, clean_credit_hours, clean_title

ACTIVATION_WINDOW_DAYS = 30

# Matches transcript/store.py's COURSE_ON_CONFLICT / DEFAULT_CREDIT_TYPE. A
# promoted planned course is written the same way a manually-entered current
# course would be: resident credit, source='manual' (it did not come off a
# parsed transcript), no letter grade yet.
COURSE_ON_CONFLICT = "student_id,term_id,course_code"
DEFAULT_CREDIT_TYPE = "resident"
DEFAULT_SOURCE = "manual"

# Editable on an in-progress course_records row. Deliberately excludes
# status='completed' -- that transition only happens through
# finalize_course_grade, which is the one place letter_grade becomes final and
# counts_flags is recomputed against the 'completed' scope. Deliberately
# excludes confirmed_at, source, catalog_course_id, counts_toward_* for the
# same reasons review.py's EDITABLE_FIELDS excludes them: they are
# system-managed or derived.
IN_PROGRESS_EDITABLE_FIELDS = ("course_code", "title", "term_id", "credit_hours", "letter_grade")

# The only status this edit surface may set. 'completed' is reached solely via
# finalize_course_grade so the final-grade gate always runs; a bare status
# edit to 'completed' would let a final grade land without ever going through
# it.
EXPLICIT_DROP_STATUS = "dropped"


class LifecycleError(ValueError):
    """Invalid input from the caller. Maps to 422."""


class CourseNotEditable(LookupError):
    """No matching row, or the row is no longer in the editable state."""


@dataclass(frozen=True)
class TermDates:
    term_id: str
    institution_id: str
    year: int
    season: str
    start_date: date | None
    end_date: date | None


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def activation_date(start_date: date) -> date:
    return start_date - timedelta(days=ACTIVATION_WINDOW_DAYS)


def is_activated(start_date: date | None, today: date) -> bool:
    """True once `today` is inside a term's pre-term activation window.

    A term with no start_date is never activated -- see the module docstring.
    """
    if start_date is None:
        return False
    return today >= activation_date(start_date)


def _term_dates_by_id(client: Any, student_id: str, institution_id: str) -> dict[str, TermDates]:
    """This student's academic_terms rows, each with its calendar dates joined
    in by (institution_id, year, season) -- the same natural-key join
    term_view.py uses, since academic_terms carries no date columns of its
    own and no FK to academic_term_dates (see that module for why not).
    """
    term_rows = rows_of(
        client.table("academic_terms")
        .select("id,institution_id,year,season")
        .eq("student_id", student_id)
        .execute()
    )
    date_rows = rows_of(
        client.table("academic_term_dates")
        .select("year,season,start_date,end_date")
        .eq("institution_id", institution_id)
        .execute()
    )
    dates_by_key: dict[tuple[int, str], Mapping[str, Any]] = {}
    for row in date_rows:
        year, season = row.get("year"), row.get("season")
        if year is None or season is None:
            continue
        dates_by_key[(int(year), str(season))] = row

    result: dict[str, TermDates] = {}
    for row in term_rows:
        year, season = row.get("year"), row.get("season")
        if year is None or season is None or row.get("id") is None:
            continue
        dates = dates_by_key.get((int(year), str(season)))
        result[str(row["id"])] = TermDates(
            term_id=str(row["id"]),
            institution_id=str(row.get("institution_id") or institution_id),
            year=int(year),
            season=str(season),
            start_date=_parse_date((dates or {}).get("start_date")),
            end_date=_parse_date((dates or {}).get("end_date")),
        )
    return result


def resolve_term_activation(
    client: Any, student_id: str, institution_id: str, year: int, season: str, today: date | None = None
) -> bool:
    """Whether the (year, season) term is already inside its activation
    window -- used by the planned-course POST route to decide whether a new
    entry belongs in planned_courses or directly in course_records.
    """
    today = today or date.today()
    date_rows = rows_of(
        client.table("academic_term_dates")
        .select("start_date")
        .eq("institution_id", institution_id)
        .eq("year", year)
        .eq("season", season)
        .execute()
    )
    if not date_rows:
        return False
    return is_activated(_parse_date(date_rows[0].get("start_date")), today)


def promote_due_planned_courses(
    client: Any, student_id: str, institution_id: str, today: date | None = None
) -> list[dict[str, Any]]:
    """Promote every planned_courses row whose term has activated.

    Idempotent and safe to call on every request: promotion is an upsert on
    course_records' existing natural key (student_id, term_id, course_code),
    so a row already promoted (by an earlier call, or entered independently)
    is a no-op skip, not a duplicate. The planned_courses row is removed once
    its slot is covered by a real course_records row either way -- a planned
    course whose promotion collided with a manually-entered row for the same
    course has still been fulfilled.
    """
    today = today or date.today()
    planned_rows = rows_of(
        client.table("planned_courses")
        .select("id,term_id,course_code,title,credit_hours,catalog_course_id")
        .eq("student_id", student_id)
        .execute()
    )
    due = [row for row in planned_rows if row.get("term_id")]
    if not due:
        return []

    term_dates = _term_dates_by_id(client, student_id, institution_id)
    promoted: list[dict[str, Any]] = []

    for row in due:
        term_id = str(row["term_id"])
        dates = term_dates.get(term_id)
        if dates is None or not is_activated(dates.start_date, today):
            continue

        payload = {
            "student_id": student_id,
            "institution_id": institution_id,
            "term_id": term_id,
            "course_code": row.get("course_code"),
            "title": row.get("title"),
            "credit_hours": row.get("credit_hours"),
            "letter_grade": None,
            "credit_type": DEFAULT_CREDIT_TYPE,
            "counts_toward_credit": False,
            "counts_toward_gpa": False,
            "status": "in_progress",
            "source": DEFAULT_SOURCE,
            "catalog_course_id": row.get("catalog_course_id"),
            "confirmed_at": now_iso(),
        }
        client.table("course_records").upsert(
            payload, ignore_duplicates=True, on_conflict=COURSE_ON_CONFLICT
        ).execute()

        client.table("planned_courses").delete().eq("id", row["id"]).eq(
            "student_id", student_id
        ).execute()

        promoted.append({"course_code": row.get("course_code"), "term_id": term_id})

    return promoted


def add_course_respecting_activation(
    client: Any,
    student_id: str,
    institution_id: str,
    *,
    term_id: str,
    year: int,
    season: str,
    course_code: Any,
    title: Any = None,
    credit_hours: Any = None,
    catalog_course_id: str | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Add one course for a term, as PLANNED or directly as IN_PROGRESS.

    If the term is already inside its activation window, the course is
    written straight into course_records with status='in_progress' -- it
    never passes through planned_courses, per the "no briefly-planned state"
    requirement. Otherwise this is a plain planned_courses insert.
    """
    activated = resolve_term_activation(client, student_id, institution_id, year, season, today)
    cleaned_code = clean_course_code(course_code)
    cleaned_title = clean_title(title)
    cleaned_hours = clean_credit_hours(credit_hours)

    if not activated:
        from .planned import add_planned

        planned = add_planned(
            client,
            student_id,
            institution_id,
            course_code=cleaned_code,
            term_id=term_id,
            title=cleaned_title,
            credit_hours=cleaned_hours,
            catalog_course_id=catalog_course_id,
        )
        return planned.to_dict()

    payload = {
        "student_id": student_id,
        "institution_id": institution_id,
        "term_id": term_id,
        "course_code": cleaned_code,
        "title": cleaned_title,
        "credit_hours": cleaned_hours,
        "letter_grade": None,
        "credit_type": DEFAULT_CREDIT_TYPE,
        "counts_toward_credit": False,
        "counts_toward_gpa": False,
        "status": "in_progress",
        "source": DEFAULT_SOURCE,
        "catalog_course_id": catalog_course_id or None,
        "confirmed_at": now_iso(),
    }
    inserted = rows_of(
        client.table("course_records")
        .upsert(payload, ignore_duplicates=True, on_conflict=COURSE_ON_CONFLICT)
        .execute()
    )
    if not inserted:
        # Natural-key collision: a course_records row for this
        # (student, term, code) already exists. Re-read it so the caller still
        # gets a row back instead of an empty response.
        inserted = rows_of(
            client.table("course_records")
            .select("*")
            .eq("student_id", student_id)
            .eq("term_id", term_id)
            .eq("course_code", cleaned_code)
            .execute()
        )
    row = inserted[0]
    return {
        "id": str(row["id"]),
        "term_id": row.get("term_id"),
        "course_code": row.get("course_code"),
        "title": row.get("title"),
        "credit_hours": float(row["credit_hours"]) if row.get("credit_hours") is not None else None,
        "letter_grade": row.get("letter_grade"),
        "status": row.get("status"),
        "kind": "in_progress",
    }


def unresolved_prior_courses(
    client: Any, student_id: str, institution_id: str, today: date | None = None
) -> list[dict[str, Any]]:
    """Confirmed, still-in-progress courses whose term has ended.

    This is the read behind "How did last semester go?" -- it never mutates
    anything, so it is safe to call on every dashboard load and will simply
    stop returning a course once finalize_course_grade completes it.
    """
    today = today or date.today()
    # confirmed_at IS NOT NULL filtered in Python, matching
    # repeats._confirmed_rows_with_terms's reasoning: the stateful `.not_`
    # property on the query builder negates whichever filter follows it,
    # which is easy to misread and easy to break on a later reorder.
    rows = [
        row
        for row in rows_of(
            client.table("course_records")
            .select("id,term_id,course_code,title,credit_hours,confirmed_at")
            .eq("student_id", student_id)
            .eq("status", "in_progress")
            .execute()
        )
        if row.get("confirmed_at") is not None
    ]
    if not rows:
        return []

    term_dates = _term_dates_by_id(client, student_id, institution_id)
    term_rows = rows_of(
        client.table("academic_terms")
        .select("id,label")
        .eq("student_id", student_id)
        .execute()
    )
    labels_by_id = {str(row["id"]): row.get("label") for row in term_rows if row.get("id")}

    unresolved: list[dict[str, Any]] = []
    for row in rows:
        term_id = row.get("term_id")
        dates = term_dates.get(str(term_id)) if term_id else None
        if dates is None or dates.end_date is None or dates.end_date >= today:
            continue
        unresolved.append(
            {
                "id": str(row["id"]),
                "term_id": str(term_id),
                "term_label": labels_by_id.get(str(term_id)),
                "course_code": row.get("course_code"),
                "title": row.get("title"),
                "credit_hours": float(row["credit_hours"]) if row.get("credit_hours") is not None else None,
            }
        )
    return unresolved


def finalize_course_grade(
    client: Any,
    student_id: str,
    course_id: str,
    letter_grade: Any,
    grade_map: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """IN_PROGRESS -> COMPLETED, storing the final letter grade.

    Idempotent: the update is scoped to status='in_progress', so calling this
    twice for the same course_id (a resubmit, a double-click, a page refresh
    that replays the request) only ever changes the row once -- the second
    call matches nothing and reports already_finalized=True rather than
    re-stamping counts_toward_gpa or double-counting anything.
    """
    if not isinstance(letter_grade, str) or not letter_grade.strip():
        raise LifecycleError("letter_grade is required to finalize a course.")
    letter_grade = letter_grade.strip()

    current = rows_of(
        client.table("course_records")
        .select("id,institution_id,status")
        .eq("id", course_id)
        .eq("student_id", student_id)
        .execute()
    )
    if not current:
        raise CourseNotEditable("No such course record.")
    row = current[0]

    if row.get("status") != "in_progress":
        return {"id": str(row["id"]), "status": row.get("status"), "already_finalized": True}

    resolved_map = grade_map or grade_map_for(client, row.get("institution_id"))
    counts_credit, counts_gpa = counts_flags(letter_grade, "completed", resolved_map)

    updated = rows_of(
        client.table("course_records")
        .update(
            {
                "letter_grade": letter_grade,
                "status": "completed",
                "counts_toward_credit": counts_credit,
                "counts_toward_gpa": counts_gpa,
                "updated_at": now_iso(),
            }
        )
        .eq("id", course_id)
        .eq("student_id", student_id)
        .eq("status", "in_progress")
        .execute()
    )
    if not updated:
        # Lost a race with a concurrent finalize of the same row -- same
        # outcome as the pre-check above.
        return {"id": course_id, "status": "completed", "already_finalized": True}

    return {"id": str(updated[0]["id"]), "status": "completed", "already_finalized": False}


def edit_in_progress_course(
    client: Any,
    student_id: str,
    course_id: str,
    body: Mapping[str, Any],
    grade_map: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Edit a confirmed, still-in-progress course_records row.

    Scoped to status='in_progress' on both the read and the write, so an
    already-completed or already-dropped row can never be reached through
    this path -- protecting finalized history is the entire reason this is a
    separate function from transcript/review.py's apply_edit rather than a
    relaxation of its confirmed_at filter.
    """
    if not isinstance(body, Mapping):
        raise LifecycleError("Request body must be a JSON object.")

    fields: dict[str, Any] = {}
    status_edit = body.get("status")

    for key in IN_PROGRESS_EDITABLE_FIELDS:
        if key not in body:
            continue
        value = body[key]
        if key == "course_code":
            fields["course_code"] = clean_course_code(value)
        elif key == "title":
            fields["title"] = clean_title(value)
        elif key == "credit_hours":
            # clean_credit_hours already enforces MAX_CREDIT_HOURS and rejects
            # negative/non-numeric input; nothing further to check here.
            fields["credit_hours"] = clean_credit_hours(value)
        elif key == "term_id":
            if value is not None and not isinstance(value, str):
                raise LifecycleError("term_id must be a string or null.")
            fields["term_id"] = value
        elif key == "letter_grade":
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise LifecycleError("letter_grade must be a non-empty string or null.")
            # This is the CURRENT grade, not the final one -- gpa.py only ever
            # reads an in_progress row's letter_grade in "projected" mode
            # (academics/gpa.py:147-152), so setting it here can never move
            # Official GPA. counts_toward_credit/gpa stay False regardless
            # (counts_flags requires status=='completed'), matching the
            # invariant that a current grade is informational only until
            # finalize_course_grade runs.
            fields["letter_grade"] = value.strip() if isinstance(value, str) else None

    if status_edit is not None:
        if status_edit != EXPLICIT_DROP_STATUS:
            raise LifecycleError(
                f"status may only be set to {EXPLICIT_DROP_STATUS!r} through this endpoint; "
                "a final grade completes a course through the finalize endpoint instead."
            )
        fields["status"] = EXPLICIT_DROP_STATUS
        fields["counts_toward_credit"] = False
        fields["counts_toward_gpa"] = False

    if not fields:
        raise LifecycleError(
            f"No editable fields supplied. Editable: "
            f"{', '.join((*IN_PROGRESS_EDITABLE_FIELDS, 'status'))}."
        )

    fields["updated_at"] = now_iso()

    updated = rows_of(
        client.table("course_records")
        .update(fields)
        .eq("id", course_id)
        .eq("student_id", student_id)
        .eq("status", "in_progress")
        .execute()
    )
    if updated:
        return updated[0]

    existing = rows_of(
        client.table("course_records")
        .select("id,status")
        .eq("id", course_id)
        .eq("student_id", student_id)
        .execute()
    )
    if not existing:
        raise CourseNotEditable("No such course record.")
    raise CourseNotEditable(
        f"This course is {existing[0].get('status')!r} and can no longer be edited here."
    )
