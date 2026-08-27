"""High-level syllabus grade-profile workflow: ingest -> correct -> confirm.

    extracted GradeModel (Phase 4/5)
        -> ingest_syllabus_extraction()      persist immutable revision
        -> apply_student_corrections()       corrections -> candidate -> re-reconcile
        -> confirm_grade_model()             student confirms an ACCEPTED model
        -> save_student_grade_state()        persist StudentGradeState
        -> get_syllabus_grade_profile()      typed read assembly

Every function takes an injected Supabase client (never constructs one --
matches transcript/resume's `client: Any` convention, letting callers pass
either build_client_for_token(...) or a test fake). No LLM calls, no PDF/
Markdown parsing -- those already happened before this module is reached.
No calculator math -- calculate_grade_projection/solve_required_score are
called by the caller against the typed result this module returns, not
from inside this module.
"""

from typing import Any

from GradusIQ_career.syllabus import read as syllabus_read
from GradusIQ_career.syllabus import store
from GradusIQ_career.syllabus.calculator import StudentGradeState
from GradusIQ_career.syllabus.corrections import GradeModelCorrection, apply_grade_model_corrections
from GradusIQ_career.syllabus.reconciliation import GradeModelReconciliationResult, ReconciliationStatus, reconcile_grade_model
from GradusIQ_career.syllabus.relevance import RelevantSyllabusContent
from GradusIQ_career.syllabus.store_helpers import now_iso


class SyllabusGradeProfileError(Exception):
    """Base class for Phase 7 service-layer failures."""


class SyllabusRevisionNotFoundError(SyllabusGradeProfileError):
    pass


class GradeModelNotAcceptedError(SyllabusGradeProfileError):
    """Raised by confirm_grade_model when the model to be confirmed --
    corrected candidate, or original extraction if no correction was ever
    applied -- is not ACCEPTED. The student cannot confirm a model that
    still needs review; there is no override path (see Phase 7 task
    section 9: "the default rule should remain: calculator-ready only
    when reconciliation == ACCEPTED").
    """


# ---------------------------------------------------------------------------
# Profile identity
# ---------------------------------------------------------------------------


def get_or_create_profile(
    client: Any,
    *,
    student_id: str,
    institution: str | None,
    course_code: str | None,
    term: str | None,
    section: str | None = None,
) -> dict:
    """Reuse an existing profile matching (student, institution, course_code,
    term) if one exists, else create one. See the migration's module
    docstring on why this lookup is not uniqueness-enforced. A caller that
    already knows a specific profile_id should read it directly via
    get_syllabus_grade_profile instead of calling this.
    """
    matches = store.find_profiles(
        client, student_id=student_id, institution=institution, course_code=course_code, term=term
    )
    if matches:
        return matches[0]
    return store.create_profile(
        client, student_id=student_id, institution=institution, course_code=course_code, term=term, section=section
    )


# ---------------------------------------------------------------------------
# Ingestion (immutable extraction history)
# ---------------------------------------------------------------------------


def ingest_syllabus_extraction(
    client: Any,
    *,
    profile_id: str,
    student_id: str,
    source_bytes: bytes,
    source_filename: str | None,
    content: RelevantSyllabusContent,
    reconciliation: GradeModelReconciliationResult,
    parsed_document_schema_version: str | None = None,
    extraction_prompt_version: str | None = None,
) -> tuple[dict, bool]:
    """Persist the immutable extraction + reconciliation result for a
    newly ingested syllabus source. Idempotent: re-ingesting byte-identical
    source content against the same profile returns the existing revision
    unchanged rather than creating a duplicate -- returns (row, created).

    A profile that was previously CONFIRMED and now receives a genuinely
    new source (different content hash) is moved to 'reconfirm_required':
    a new source must never silently inherit an old confirmation.
    """
    grade_model = reconciliation.grade_model
    source_hash = store.content_hash(source_bytes)

    revision, created = store.insert_revision(
        client,
        profile_id=profile_id,
        student_id=student_id,
        source_filename=source_filename,
        source_content_hash=source_hash,
        source_page_count=content.source_page_count,
        parsed_document_schema_version=parsed_document_schema_version,
        relevant_content_schema_version=content.schema_version,
        extraction_prompt_version=extraction_prompt_version,
        grade_model_schema_version=grade_model.schema_version,
        extracted_grade_model=grade_model.model_dump(mode="json"),
        relevant_content=content.model_dump(mode="json"),
        reconciliation_status=reconciliation.status.value,
        reconciliation_findings=[f.model_dump(mode="json") for f in reconciliation.findings],
        evidence_coverage=reconciliation.evidence_coverage.model_dump(mode="json"),
    )

    if created:
        profile = store.get_profile(client, profile_id=profile_id, student_id=student_id)
        review_state = "needs_review"
        if profile is not None and profile.get("review_state") == "confirmed":
            review_state = "reconfirm_required"
        store.update_profile_state(
            client,
            profile_id=profile_id,
            student_id=student_id,
            review_state=review_state,
            current_revision_id=revision["id"],
        )

    return revision, created


# ---------------------------------------------------------------------------
# Corrections (never bypass Phase 5)
# ---------------------------------------------------------------------------


def apply_student_corrections(
    client: Any,
    *,
    revision_id: str,
    student_id: str,
    corrections: list[GradeModelCorrection],
) -> dict:
    """extracted GradeModel + corrections -> candidate -> reconcile again.

    The candidate is persisted regardless of whether its own reconciliation
    comes back ACCEPTED or NEEDS_STUDENT_REVIEW -- corrections are never
    treated as calculator-ready just because the student supplied them
    (Phase 5's trust gate applies unconditionally to the candidate, exactly
    as if it had been freshly extracted). Use confirm_grade_model to
    actually mark a (now-accepted) candidate as the student's confirmed
    model.
    """
    revision = store.get_revision(client, revision_id=revision_id, student_id=student_id)
    if revision is None:
        raise SyllabusRevisionNotFoundError(f"no syllabus grade revision {revision_id} for this student")

    extracted_model = syllabus_read.extracted_grade_model_from_row(revision)
    content = syllabus_read.relevant_content_from_row(revision)

    candidate = apply_grade_model_corrections(extracted_model, corrections)
    candidate_reconciliation = reconcile_grade_model(candidate, content)

    return store.update_revision_confirmation(
        client,
        revision_id=revision_id,
        student_id=student_id,
        corrections=[c.model_dump(mode="json") for c in corrections],
        confirmed_grade_model=candidate.model_dump(mode="json"),
        confirmed_reconciliation_status=candidate_reconciliation.status.value,
        confirmed_at=None,
    )


def confirm_grade_model(client: Any, *, revision_id: str, student_id: str) -> dict:
    """The student's explicit confirmation of a calculator-ready model.

    Confirms the corrected candidate if apply_student_corrections was ever
    called for this revision; otherwise confirms the original extraction
    unmodified (section 14: "If Phase 5 already returns ACCEPTED, the
    student may confirm without modifications" -- no fake correction
    entries are created for that case). Either way, raises
    GradeModelNotAcceptedError rather than confirming a model whose
    reconciliation is NEEDS_STUDENT_REVIEW.
    """
    revision = store.get_revision(client, revision_id=revision_id, student_id=student_id)
    if revision is None:
        raise SyllabusRevisionNotFoundError(f"no syllabus grade revision {revision_id} for this student")

    if revision.get("confirmed_grade_model") is not None:
        status = revision.get("confirmed_reconciliation_status")
        confirmed_model = revision["confirmed_grade_model"]
        corrections = revision.get("corrections", [])
    else:
        status = revision["reconciliation_status"]
        confirmed_model = revision["extracted_grade_model"]
        corrections = []

    if status != ReconciliationStatus.ACCEPTED.value:
        raise GradeModelNotAcceptedError(f"cannot confirm: reconciliation status is '{status}', not accepted")

    updated_revision = store.update_revision_confirmation(
        client,
        revision_id=revision_id,
        student_id=student_id,
        corrections=corrections,
        confirmed_grade_model=confirmed_model,
        confirmed_reconciliation_status=status,
        confirmed_at=now_iso(),
    )
    store.update_profile_state(
        client,
        profile_id=revision["profile_id"],
        student_id=student_id,
        review_state="confirmed",
        current_revision_id=revision_id,
    )
    return updated_revision


# ---------------------------------------------------------------------------
# StudentGradeState
# ---------------------------------------------------------------------------


def save_student_grade_state(
    client: Any,
    *,
    profile_id: str,
    student_id: str,
    grade_state: StudentGradeState,
    expected_revision: int | None = None,
) -> dict:
    """Explicit, opt-in persistence of a StudentGradeState. Nothing in this
    package calls this automatically on the caller's behalf just because a
    what-if projection was computed elsewhere -- a transient
    calculate_grade_projection() call with hypothetical/projected scores
    never touches this table unless the caller separately chooses to save.
    """
    return store.save_grade_state(
        client,
        profile_id=profile_id,
        student_id=student_id,
        category_scores=[c.model_dump(mode="json") for c in grade_state.category_scores],
        assessment_scores=[a.model_dump(mode="json") for a in grade_state.assessment_scores],
        expected_revision=expected_revision,
    )


# ---------------------------------------------------------------------------
# Read assembly
# ---------------------------------------------------------------------------


def get_syllabus_grade_profile(client: Any, *, profile_id: str, student_id: str) -> dict | None:
    """Assemble the full typed workflow state for one profile: the profile
    row, its current revision (typed extracted/confirmed GradeModel +
    reconciliation), full revision history, saved grade state if any, and
    the single deterministic calculator_ready flag.
    """
    profile = store.get_profile(client, profile_id=profile_id, student_id=student_id)
    if profile is None:
        return None

    revisions = store.list_revisions(client, profile_id=profile_id, student_id=student_id)
    current_revision = None
    if profile.get("current_revision_id") is not None:
        current_revision = next((r for r in revisions if r["id"] == profile["current_revision_id"]), None)

    grade_state_row = store.get_grade_state(client, profile_id=profile_id, student_id=student_id)

    return {
        "profile": profile,
        "current_revision": current_revision,
        "revisions": revisions,
        "extracted_grade_model": (
            syllabus_read.extracted_grade_model_from_row(current_revision) if current_revision else None
        ),
        "confirmed_grade_model": (
            syllabus_read.confirmed_grade_model_from_row(current_revision) if current_revision else None
        ),
        "reconciliation": (
            syllabus_read.reconciliation_result_from_row(current_revision) if current_revision else None
        ),
        "grade_state": syllabus_read.grade_state_from_row(grade_state_row) if grade_state_row else None,
        "grade_state_revision": grade_state_row.get("revision") if grade_state_row else None,
        "calculator_ready": syllabus_read.calculator_ready(profile, current_revision),
    }
