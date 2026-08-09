"""Persist parsed transcript data through a session-scoped (RLS) client.

Every function here takes a client built by
CampusIQ_career.supabase_client.build_client_for_token, so Postgres RLS
narrows all reads and writes to the caller's own rows. This module must never
construct its own client and must never read SUPABASE_SECRET_KEY.

DUPLICATE HANDLING
------------------
course_records carries course_records_student_term_course_key on
(student_id, term_id, course_code) WITH NULLS NOT DISTINCT
(20260728035418:69-72). NULLS NOT DISTINCT matters here specifically because
term_id IS NULLABLE and this module writes null term_id for any course whose
term label could not be resolved -- under a plain unique index two such rows
would both insert; under this one the second collides.

Writes go through .upsert(..., ignore_duplicates=True, on_conflict=...) ->
ON CONFLICT DO NOTHING, one row at a time. Two reasons it is per-row rather
than one batch call, both real:

  1. A batch upsert whose payload contains two rows with the same conflict key
     raises Postgres 21000 ("ON CONFLICT DO UPDATE command cannot affect row a
     second time") on DO UPDATE, and on DO NOTHING silently keeps only one --
     with no way to tell which. Transcripts produce exactly this: two rows with
     null term_id and the same course_code collapse to one key. Per-row writes
     turn that into a countable skipped_duplicate.
  2. With the default returning=representation, an inserted row comes back in
     .data and a skipped duplicate comes back as [] -- which is how inserted
     and skipped are counted apart with no follow-up read. This is the same
     technique resume/store.py uses.

DO NOTHING, NOT DO UPDATE -- a re-upload never overwrites an existing row.
A student may have already reviewed, edited, or confirmed that row; a second
upload silently rewriting a corrected grade would be a correctness bug, not a
merge. Reconciling a re-upload against existing rows is a review-screen
decision, the same call ensure_career_profile makes in resume/store.py.

DEFERRED, NOT SKIPPED
---------------------
Repeat detection (course_records.excluded_from_gpa_by, added by migration
20260729193925) is NOT populated here. Deciding which attempt a repeat
supersedes requires a second pass over rows that must already exist -- it is a
self-referencing FK, so the superseding row needs an id before the superseded
row can point at it -- plus the institution's repeat_policy. That is its own
stage. Until it lands, a student who repeated a course has both attempts
counted, which is correct for TAMU (all_attempts_count) and wrong for SMU
(latest_replaces).
"""

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable, Mapping

from .parser import ParsedTranscript
from .repeats import reconcile_repeats
from .store_helpers import now_iso, rows_of


logger = logging.getLogger(__name__)


TRANSCRIPT_SOURCE = "transcript_parse"

# Backs course_records_student_term_course_key. A conflict target that does not
# match a live index raises 42P10 loudly rather than silently choosing another
# index, so a wrong value here fails fast instead of overwriting a wrong row.
COURSE_ON_CONFLICT = "student_id,term_id,course_code"

# course_records.credit_type is NOT NULL with a CHECK constraint. The transcript
# contract does not ask the model to classify credit type: distinguishing
# resident from transfer from dual-enrollment reliably needs the institution
# block headings a transcript prints around them, and getting it wrong changes
# GPA inclusion (gpa.py excludes exam credit entirely, and transfer credit
# unless the institution says otherwise). Everything is written as 'resident',
# which is the correct value for the overwhelming majority of rows on a
# home-institution transcript and the safest wrong answer for the rest: it
# includes a course in the GPA rather than silently excluding it, so an error
# is visible in a number the student recognizes rather than hidden as a missing
# course. Classifying credit_type properly is deferred with repeat detection.
DEFAULT_CREDIT_TYPE = "resident"


class ConfirmBlocked(Exception):
    """Confirmation is not available for this student's institution(s).

    Raised only by the Part 0 grade-scale gate. The route maps it to a 409;
    it is not an error in the request, it is a state the student can do
    nothing about and must be told about plainly.
    """


@dataclass
class TableWriteReport:
    inserted: int = 0
    skipped_duplicate: int = 0

    def to_dict(self) -> dict[str, int]:
        return {"inserted": self.inserted, "skipped_duplicate": self.skipped_duplicate}


@dataclass
class StoreReport:
    courses: TableWriteReport = field(default_factory=TableWriteReport)
    terms_created: int = 0
    terms_reused: int = 0
    # Term labels that could not be resolved; their courses were written with
    # a null term_id rather than filed under a guessed semester.
    unresolved_terms: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "written": {"course_records": self.courses.to_dict()},
            "terms": {
                "created": self.terms_created,
                "reused": self.terms_reused,
                "unresolved": self.unresolved_terms,
            },
        }


def grade_map_for(client: Any, institution_id: str) -> dict[str, dict[str, Any]]:
    """letter -> its grade_point_map row, for one institution.

    grade_point_map is public-read (grade_point_map_read_public), so the
    session-scoped client can read it directly.
    """
    rows = rows_of(
        client.table("grade_point_map")
        .select("*")
        .eq("institution_id", institution_id)
        .execute()
    )
    return {row["letter"]: row for row in rows if row.get("letter")}


def counts_flags(
    letter_grade: str | None,
    status: str,
    grade_map: Mapping[str, Mapping[str, Any]],
) -> tuple[bool, bool]:
    """Return (counts_toward_credit, counts_toward_gpa) for one course row.

    THESE TWO COLUMNS ARE INFORMATIONAL / DISPLAY ONLY.

    academics/gpa.py is the source of truth for GPA computation, and it does
    NOT read these columns. It re-resolves every record's letter through
    resolve_grade() against the institution's live grade_point_map, and applies
    its own status, credit_type, confirmed_at and excluded_from_gpa_by rules on
    top. A row stored here with counts_toward_gpa=true is still excluded by
    gpa.py if it is unconfirmed, or exam credit, or superseded by a repeat.

    So do not "fix" a GPA discrepancy by editing these columns -- they cannot
    move a GPA. They exist so a review screen can show the student why a course
    is or is not expected to count, without re-deriving grade resolution in the
    frontend. If they disagree with gpa.py, gpa.py is right and this function
    is the bug.

    The rule, deliberately simple: an in-progress course counts toward neither
    (it has no final grade to score). A completed course inherits both flags
    from its grade_point_map row -- which is what makes W and I come out false,
    and SMU's P come out credit-yes / gpa-no. A letter absent from the map
    counts toward neither; the parser rejects those before they reach here, so
    this branch only fires for rows written by some other path.
    """
    if status != "completed":
        return False, False

    if letter_grade is None:
        return False, False

    row = grade_map.get(letter_grade)
    if row is None:
        return False, False

    return bool(row.get("counts_toward_credit")), bool(row.get("counts_toward_gpa"))


def _course_payload(
    course: Mapping[str, Any],
    *,
    student_id: str,
    institution_id: str,
    term_id: str | None,
    grade_map: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    letter_grade = course.get("letter_grade")
    status = str(course.get("status"))
    counts_credit, counts_gpa = counts_flags(letter_grade, status, grade_map)

    credit_hours = course.get("credit_hours")
    if isinstance(credit_hours, Decimal):
        # PostgREST serializes the payload as JSON, which has no Decimal.
        # str() preserves the exact scale the parser quantized to; float()
        # would reintroduce binary rounding on a numeric(4,2) column.
        credit_hours = str(credit_hours)

    return {
        "student_id": student_id,
        "institution_id": institution_id,
        "term_id": term_id,
        "course_code": course.get("course_code"),
        "title": course.get("title"),
        "credit_hours": credit_hours,
        "letter_grade": letter_grade,
        "credit_type": DEFAULT_CREDIT_TYPE,
        "counts_toward_credit": counts_credit,
        "counts_toward_gpa": counts_gpa,
        "status": status,
        "source": TRANSCRIPT_SOURCE,
        "catalog_course_id": course.get("catalog_course_id"),
        "confirmed_at": None,
    }


def store_parsed_transcript(
    client: Any,
    student_id: str,
    institution_id: str,
    parsed: ParsedTranscript,
    *,
    term_id_by_label: Mapping[str, str],
    unresolved_terms: Mapping[str, str] | None = None,
    terms_created: int = 0,
    terms_reused: int = 0,
    grade_map: Mapping[str, Mapping[str, Any]] | None = None,
) -> StoreReport:
    """Write a parsed transcript's course rows. Caller checks parsed.status.

    Term resolution and catalog matching happen before this call (terms.py and
    catalog.py); this function writes what they produced.
    """
    resolved_map = grade_map if grade_map is not None else grade_map_for(client, institution_id)

    report = StoreReport(
        terms_created=terms_created,
        terms_reused=terms_reused,
        unresolved_terms=dict(unresolved_terms or {}),
    )

    for course in parsed.courses:
        label = course.get("term_label")
        payload = _course_payload(
            course,
            student_id=student_id,
            institution_id=institution_id,
            term_id=term_id_by_label.get(label) if label else None,
            grade_map=resolved_map,
        )
        response = (
            client.table("course_records")
            .upsert(payload, ignore_duplicates=True, on_conflict=COURSE_ON_CONFLICT)
            .execute()
        )
        if rows_of(response):
            report.courses.inserted += 1
        else:
            report.courses.skipped_duplicate += 1

    return report


# -- confirmation -------------------------------------------------------------


def unverified_institutions(
    client: Any, institution_ids: Iterable[str]
) -> list[dict[str, Any]]:
    """Institutions among `institution_ids` whose grade scale is unverified.

    institutions is public-read (institutions_read_public).

    An id with no visible row is treated as UNVERIFIED, not as verified. A
    missing row means we cannot establish that the scale was checked, and the
    whole point of this gate is that unestablished means blocked.
    """
    wanted = sorted({i for i in institution_ids if i})
    if not wanted:
        return []

    rows = rows_of(
        client.table("institutions")
        .select("id,name,grade_scale_verified")
        .in_("id", wanted)
        .execute()
    )
    by_id = {row["id"]: row for row in rows if row.get("id")}

    unverified: list[dict[str, Any]] = []
    for institution_id in wanted:
        row = by_id.get(institution_id)
        if row is None:
            unverified.append({"id": institution_id, "name": "this institution"})
        elif not row.get("grade_scale_verified"):
            unverified.append(
                {"id": institution_id, "name": row.get("name") or "this institution"}
            )
    return unverified


def confirm_course_rows(
    client: Any,
    student_id: str,
    *,
    selection: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Stamp confirmed_at on this student's unconfirmed course_records.

    With `selection` omitted, confirms every still-unconfirmed row. With a
    selection, confirms only the named ids.

    THE GRADE-SCALE GATE (Part 0). Confirmation is what makes a row
    GPA-eligible -- gpa.py excludes every record whose confirmed_at is null. So
    this is the last point at which an unverified grade scale can be stopped
    before it starts producing a number shown to a student. The institutions of
    the rows actually being confirmed are checked, not the student's home
    institution: a transfer block on the transcript can carry a different
    institution_id, and it is that institution's scale that would score it.

    Raises ConfirmBlocked, writing nothing, if any is unverified. Upload,
    parse, review and edit are all unaffected by this gate -- only this call.

    Two filters are always applied and are not caller-controllable:
      * .eq("student_id", student_id) -- belt and braces alongside RLS.
      * .is_("confirmed_at", "null") -- so re-running never rewrites an
        earlier confirmation timestamp.
    """
    pending = rows_of(
        client.table("course_records")
        .select("id,institution_id")
        .eq("student_id", student_id)
        .is_("confirmed_at", "null")
        .execute()
    )

    ids = [str(value) for value in selection] if selection is not None else None
    if ids is not None:
        wanted = set(ids)
        pending = [row for row in pending if row.get("id") in wanted]

    if not pending:
        # "repeats" is present-but-null rather than absent, so the response
        # shape is the same on every path. Nothing was newly confirmed, so
        # there is nothing for reconciliation to reconsider: exclusions are a
        # function of the confirmed set, which did not change.
        return {
            "confirmed": 0,
            "scope": "selection" if ids is not None else "all_unconfirmed",
            "repeats": None,
        }

    blocked = unverified_institutions(
        client, [row.get("institution_id") for row in pending]
    )
    if blocked:
        names = ", ".join(sorted({row["name"] for row in blocked}))
        raise ConfirmBlocked(
            f"Course records for {names} can't be confirmed yet - grade scale "
            "verification is pending. Your transcript has been parsed and saved "
            "for review, but confirmation is temporarily unavailable."
        )

    stamp = now_iso()
    query = (
        client.table("course_records")
        .update({"confirmed_at": stamp, "updated_at": stamp})
        .eq("student_id", student_id)
        .is_("confirmed_at", "null")
    )
    if ids is not None:
        query = query.in_("id", ids)

    confirmed = rows_of(query.execute())

    # AFTER the stamp, never before. Repeat exclusion is only meaningful among
    # rows that are already counting toward the GPA: running it earlier would
    # let a still-unconfirmed second attempt exclude an already-confirmed first
    # attempt, dropping the course out of the GPA entirely until the student
    # happened to confirm the second row. See repeats.py's module docstring.
    #
    # Deliberately NOT inside the try/except the route wraps this in as a fatal
    # error: a reconciliation failure must not roll back or obscure a
    # confirmation that already succeeded. The rows are confirmed; the
    # exclusions are recomputed from scratch on the next confirm regardless.
    repeats: dict[str, Any] | None = None
    try:
        repeats = reconcile_repeats(client, student_id).to_dict()
    except Exception:  # noqa: BLE001 -- confirmation already succeeded
        logger.exception(
            "repeat reconciliation failed after confirming rows for student %s; "
            "confirmation stands and exclusions will be recomputed on the next run",
            student_id,
        )

    return {
        "confirmed": len(confirmed),
        "scope": "selection" if ids is not None else "all_unconfirmed",
        "repeats": repeats,
    }
