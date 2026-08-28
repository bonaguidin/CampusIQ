"""Supabase I/O for syllabus grade profiles/revisions/grade-state.

Thin layer: builds plain dict payloads from already-validated Pydantic
models, issues PostgREST calls via the injected client, and returns raw
rows. No domain logic lives here -- see service.py for
ingest/correct/confirm orchestration, and read.py for reconstructing typed
models from these raw rows. Mirrors transcript/store.py's shape (plain
`client.table(...).select/insert/update(...)` calls, no ORM).
"""

import hashlib
from typing import Any

from GradusIQ_career.syllabus.store_helpers import now_iso, rows_of

PROFILES_TABLE = "syllabus_grade_profiles"
REVISIONS_TABLE = "syllabus_grade_revisions"
GRADE_STATES_TABLE = "syllabus_grade_states"


class GradeStateConflictError(Exception):
    """Raised on an optimistic-concurrency conflict: the caller's
    `expected_revision` does not match the currently stored revision.
    """


def content_hash(data: bytes) -> str:
    """SHA-256 of raw source bytes, in the repo's existing "sha256:<hex>"
    content-hash format (see degree_schedule_version.py/requirement_group
    decision_version for precedent).
    """
    return "sha256:" + hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


def find_profiles(
    client: Any,
    *,
    student_id: str,
    institution: str | None,
    course_code: str | None,
    term: str | None,
) -> list[dict]:
    """Non-unique lookup -- see migration module docstring on why course
    identity has no uniqueness constraint (GradeModel.course fields are
    free-text/nullable, unlike a validated catalog course row).
    """
    query = client.table(PROFILES_TABLE).select("*").eq("student_id", student_id)
    if institution is not None:
        query = query.eq("institution", institution)
    if course_code is not None:
        query = query.eq("course_code", course_code)
    if term is not None:
        query = query.eq("term", term)
    return rows_of(query.execute())


def list_profiles(client: Any, *, student_id: str) -> list[dict]:
    """All profiles for a student -- cheap, read-only, no parsing/LLM."""
    response = client.table(PROFILES_TABLE).select("*").eq("student_id", student_id).execute()
    return rows_of(response)


def get_profile(client: Any, *, profile_id: str, student_id: str) -> dict | None:
    response = (
        client.table(PROFILES_TABLE).select("*").eq("id", profile_id).eq("student_id", student_id).execute()
    )
    rows = rows_of(response)
    return rows[0] if rows else None


def create_profile(
    client: Any,
    *,
    student_id: str,
    institution: str | None,
    course_code: str | None,
    term: str | None,
    section: str | None,
) -> dict:
    payload = {
        "student_id": student_id,
        "institution": institution,
        "course_code": course_code,
        "term": term,
        "section": section,
        "review_state": "needs_review",
    }
    response = client.table(PROFILES_TABLE).insert(payload).execute()
    rows = rows_of(response)
    if not rows:
        raise RuntimeError("syllabus_grade_profiles insert returned no row")
    return rows[0]


def update_profile_state(
    client: Any,
    *,
    profile_id: str,
    student_id: str,
    review_state: str,
    current_revision_id: str | None,
) -> dict:
    payload = {"review_state": review_state, "current_revision_id": current_revision_id, "updated_at": now_iso()}
    response = (
        client.table(PROFILES_TABLE)
        .update(payload)
        .eq("id", profile_id)
        .eq("student_id", student_id)
        .execute()
    )
    rows = rows_of(response)
    if not rows:
        raise RuntimeError(f"syllabus_grade_profiles update affected no row for id={profile_id}")
    return rows[0]


# ---------------------------------------------------------------------------
# Revisions (immutable extraction history)
# ---------------------------------------------------------------------------


def list_revisions(client: Any, *, profile_id: str, student_id: str) -> list[dict]:
    response = (
        client.table(REVISIONS_TABLE)
        .select("*")
        .eq("profile_id", profile_id)
        .eq("student_id", student_id)
        .order("created_at", desc=True)
        .execute()
    )
    return rows_of(response)


def get_revision(client: Any, *, revision_id: str, student_id: str) -> dict | None:
    response = (
        client.table(REVISIONS_TABLE).select("*").eq("id", revision_id).eq("student_id", student_id).execute()
    )
    rows = rows_of(response)
    return rows[0] if rows else None


def find_revision_by_hash(client: Any, *, profile_id: str, source_content_hash: str) -> dict | None:
    response = (
        client.table(REVISIONS_TABLE)
        .select("*")
        .eq("profile_id", profile_id)
        .eq("source_content_hash", source_content_hash)
        .execute()
    )
    rows = rows_of(response)
    return rows[0] if rows else None


def insert_revision(
    client: Any,
    *,
    profile_id: str,
    student_id: str,
    source_filename: str | None,
    source_content_hash: str,
    source_page_count: int | None,
    parsed_document_schema_version: str | None,
    relevant_content_schema_version: str | None,
    extraction_prompt_version: str | None,
    grade_model_schema_version: str,
    extracted_grade_model: dict,
    relevant_content: dict,
    reconciliation_status: str,
    reconciliation_findings: list[dict],
    evidence_coverage: dict,
) -> tuple[dict, bool]:
    """Insert a new immutable revision, or return the existing one if this
    exact source (profile_id, source_content_hash) was already ingested --
    the idempotency behavior for "student uploads the same syllabus twice"
    (see the unique constraint in the migration).

    Returns (row, created) -- created is False on an idempotent hit.
    """
    existing = find_revision_by_hash(client, profile_id=profile_id, source_content_hash=source_content_hash)
    if existing is not None:
        return existing, False

    payload = {
        "profile_id": profile_id,
        "student_id": student_id,
        "source_filename": source_filename,
        "source_content_hash": source_content_hash,
        "source_page_count": source_page_count,
        "parsed_document_schema_version": parsed_document_schema_version,
        "relevant_content_schema_version": relevant_content_schema_version,
        "extraction_prompt_version": extraction_prompt_version,
        "grade_model_schema_version": grade_model_schema_version,
        "extracted_grade_model": extracted_grade_model,
        "relevant_content": relevant_content,
        "reconciliation_status": reconciliation_status,
        "reconciliation_findings": reconciliation_findings,
        "evidence_coverage": evidence_coverage,
    }
    response = client.table(REVISIONS_TABLE).insert(payload).execute()
    rows = rows_of(response)
    if not rows:
        raise RuntimeError("syllabus_grade_revisions insert returned no row")
    return rows[0], True


def update_revision_confirmation(
    client: Any,
    *,
    revision_id: str,
    student_id: str,
    corrections: list[dict],
    confirmed_grade_model: dict,
    confirmed_reconciliation_status: str,
    confirmed_at: str | None,
) -> dict:
    """The only permitted UPDATE on a revision -- never touches
    extracted_grade_model/source_content_hash/reconciliation_status
    (also enforced by a DB trigger; see the migration).
    """
    payload = {
        "corrections": corrections,
        "confirmed_grade_model": confirmed_grade_model,
        "confirmed_reconciliation_status": confirmed_reconciliation_status,
        "confirmed_at": confirmed_at,
        "updated_at": now_iso(),
    }
    response = (
        client.table(REVISIONS_TABLE)
        .update(payload)
        .eq("id", revision_id)
        .eq("student_id", student_id)
        .execute()
    )
    rows = rows_of(response)
    if not rows:
        raise RuntimeError(f"syllabus_grade_revisions update affected no row for id={revision_id}")
    return rows[0]


# ---------------------------------------------------------------------------
# Grade state (StudentGradeState)
# ---------------------------------------------------------------------------


def get_grade_state(client: Any, *, profile_id: str, student_id: str) -> dict | None:
    response = (
        client.table(GRADE_STATES_TABLE)
        .select("*")
        .eq("profile_id", profile_id)
        .eq("student_id", student_id)
        .execute()
    )
    rows = rows_of(response)
    return rows[0] if rows else None


def save_grade_state(
    client: Any,
    *,
    profile_id: str,
    student_id: str,
    category_scores: list[dict],
    assessment_scores: list[dict],
    expected_revision: int | None = None,
) -> dict:
    """Explicit save of a StudentGradeState -- an opt-in action, not
    triggered automatically by a transient what-if calculation (see
    module docstring / service.py: nothing calls this on the caller's
    behalf just because calculate_grade_projection() was invoked).

    Optimistic concurrency: pass `expected_revision` (the caller's last
    known `revision`) to guard against a lost update from a concurrent
    save; a mismatch raises GradeStateConflictError rather than silently
    overwriting. Omit it to force an unconditional write.
    """
    existing = get_grade_state(client, profile_id=profile_id, student_id=student_id)
    now = now_iso()

    if existing is None:
        if expected_revision is not None:
            raise GradeStateConflictError("expected_revision given for a grade state that does not exist yet")
        payload = {
            "profile_id": profile_id,
            "student_id": student_id,
            "category_scores": category_scores,
            "assessment_scores": assessment_scores,
            "revision": 1,
            "updated_at": now,
        }
        response = client.table(GRADE_STATES_TABLE).insert(payload).execute()
        rows = rows_of(response)
        if not rows:
            raise GradeStateConflictError("grade state insert affected no row (possible concurrent creation)")
        return rows[0]

    if expected_revision is not None and expected_revision != existing["revision"]:
        raise GradeStateConflictError(
            f"expected revision {expected_revision}, stored revision is {existing['revision']}"
        )

    payload = {
        "category_scores": category_scores,
        "assessment_scores": assessment_scores,
        "revision": existing["revision"] + 1,
        "updated_at": now,
    }
    query = (
        client.table(GRADE_STATES_TABLE)
        .update(payload)
        .eq("id", existing["id"])
        .eq("student_id", student_id)
        .eq("revision", existing["revision"])
    )
    rows = rows_of(query.execute())
    if not rows:
        raise GradeStateConflictError("grade state was updated concurrently; reload and retry")
    return rows[0]
