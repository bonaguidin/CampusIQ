"""Service-level Phase 7 tests: ingest -> correct -> confirm -> read, against
an in-memory fake Supabase client (PostgREST's chainable .table().select()/
.insert()/.update().eq().execute() shape only -- no RLS/constraint
enforcement here; those are covered by the real local-Postgres migration
test in test_syllabus_grade_profiles_migration.py).
"""

import uuid as uuid_lib

import pytest

from GradusIQ_career.syllabus import service
from GradusIQ_career.syllabus.calculator import (
    AssessmentScoreInput,
    CategoryScoreInput,
    GradeModelNotReadyError,
    ScoreStatus,
    StudentGradeState,
    calculate_grade_projection,
)
from GradusIQ_career.syllabus.corrections import (
    CorrectionApplicationError,
    CorrectionOperation,
    CorrectionTargetType,
    GradeModelCorrection,
)
from GradusIQ_career.syllabus.models import (
    Assessment,
    ExtractionWarning,
    ExtractionWarningType,
    GradeCategory,
    GradeModel,
    GradeThreshold,
    GradingMethod,
    GradingRule,
    GradingRuleType,
    SourceEvidence,
)
from GradusIQ_career.syllabus.reconciliation import ReconciliationStatus, reconcile_grade_model
from GradusIQ_career.syllabus.relevance import RelevantPage, RelevantSyllabusContent
from GradusIQ_career.syllabus.store import GradeStateConflictError
from GradusIQ_career.syllabus.store_helpers import now_iso

STUDENT_A = "10000000-0000-0000-0000-000000000001"
STUDENT_B = "10000000-0000-0000-0000-000000000002"


# --- in-memory fake Supabase client -------------------------------------------------


class _FakeResponse:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, table, op, payload=None):
        self.table = table
        self.op = op
        self.payload = payload
        self.filters = []
        self.null_filters = []
        self._order = None

    def eq(self, col, val):
        self.filters.append((col, val))
        return self

    def is_(self, col, val):
        assert val == "null", f"_FakeQuery.is_ only supports 'null', got {val!r}"
        self.null_filters.append(col)
        return self

    def order(self, col, desc=False):
        self._order = (col, desc)
        return self

    def execute(self):
        return self.table._execute(self)


class _FakeTable:
    def __init__(self, client, name):
        self.client = client
        self.name = name

    def select(self, *_args):
        return _FakeQuery(self, "select")

    def insert(self, payload):
        return _FakeQuery(self, "insert", payload)

    def update(self, payload):
        return _FakeQuery(self, "update", payload)

    def _rows(self):
        return self.client.data.setdefault(self.name, [])

    def _matched(self, query):
        return [
            r
            for r in self._rows()
            if all(r.get(c) == v for c, v in query.filters)
            and all(r.get(c) is None for c in query.null_filters)
        ]

    def _execute(self, query):
        if query.op == "select":
            matched = self._matched(query)
            if query._order:
                col, desc = query._order
                matched = sorted(matched, key=lambda r: r.get(col) or "", reverse=desc)
            return _FakeResponse([dict(r) for r in matched])
        if query.op == "insert":
            row = dict(query.payload)
            row.setdefault("id", str(uuid_lib.uuid4()))
            row.setdefault("created_at", now_iso())
            row.setdefault("updated_at", now_iso())
            if self.name == "syllabus_grade_revisions":
                row.setdefault("corrections", [])
                row.setdefault("confirmed_grade_model", None)
                row.setdefault("confirmed_reconciliation_status", None)
                row.setdefault("confirmed_at", None)
            if self.name == "syllabus_grade_profiles":
                row.setdefault("current_revision_id", None)
                row.setdefault("deleted_at", None)
            self._rows().append(row)
            return _FakeResponse([dict(row)])
        if query.op == "update":
            matched = self._matched(query)
            for row in matched:
                row.update(query.payload)
            return _FakeResponse([dict(r) for r in matched])
        raise NotImplementedError(query.op)


class FakeSupabaseClient:
    def __init__(self):
        self.data: dict[str, list[dict]] = {}

    def table(self, name):
        return _FakeTable(self, name)


@pytest.fixture
def client():
    return FakeSupabaseClient()


# --- fixtures ------------------------------------------------------------------------


def evidence(page_number: int, text: str) -> SourceEvidence:
    return SourceEvidence(page=page_number, text=text, confidence=1.0)


def content_for(*texts: str) -> RelevantSyllabusContent:
    pages = [RelevantPage(page_number=i + 1, markdown=text, relevance_score=5.0) for i, text in enumerate(texts)]
    combined = "\n\n".join(f"<!-- page: {p.page_number} -->\n\n{p.markdown}" for p in pages)
    return RelevantSyllabusContent(
        selected_pages=pages, selected_sections=[], markdown=combined, source_page_count=len(pages), selected_page_count=len(pages)
    )


def clean_model() -> GradeModel:
    return GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        categories=[
            GradeCategory(name="Midterm", weight=30, evidence=evidence(1, "Midterm: 30%")),
            GradeCategory(name="Final", weight=40, evidence=evidence(1, "Final: 40%")),
            GradeCategory(name="Project", weight=30, evidence=evidence(1, "Project: 30%")),
        ],
        grade_thresholds=[
            GradeThreshold(letter="A", minimum=90, maximum=100, evidence=evidence(1, "A: 90-100")),
            GradeThreshold(letter="F", maximum=59, evidence=evidence(1, "F: below 60")),
        ],
    )


CLEAN_CONTENT = content_for("Midterm: 30% Final: 40% Project: 30% A: 90-100 F: below 60")


def phys_207_with_curve() -> GradeModel:
    return GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        categories=[
            GradeCategory(name="Mid-term Exam", weight=35, evidence=evidence(1, "Mid-term Exam: 35%")),
            GradeCategory(name="Final Exam", weight=50, evidence=evidence(1, "Final Exam: 50%")),
            GradeCategory(name="Lecture Quizzes", weight=5, evidence=evidence(1, "Lecture Quizzes: 5%")),
            GradeCategory(name="Recitation Quizzes", weight=10, evidence=evidence(1, "Recitation Quizzes: 10%")),
        ],
        rules=[
            GradingRule(
                rule_type=GradingRuleType.CURVE,
                description="Grades may be curved upward.",
                evidence=evidence(1, "Grades may be curved upward."),
            )
        ],
    )


PHYS_207_CONTENT = content_for(
    "Mid-term Exam: 35% Final Exam: 50% Lecture Quizzes: 5% Recitation Quizzes: 10% Grades may be curved upward."
)


def needs_review_model() -> GradeModel:
    """A model that genuinely needs student review for a reason unrelated to
    any informational (curve/late-work/makeup) rule: a replacement rule
    whose target names a category that does not exist.
    """
    return GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        categories=[
            GradeCategory(name="Midterm", weight=50, evidence=evidence(1, "Midterm: 50%")),
            GradeCategory(name="Final", weight=50, evidence=evidence(1, "Final: 50%")),
        ],
        rules=[
            GradingRule(
                rule_type=GradingRuleType.REPLACEMENT,
                description="Final replaces the makeup exam when higher.",
                source="Final",
                target="Makeup Exam",
                condition="final_score > makeup_score",
                evidence=evidence(1, "Final replaces the makeup exam when higher."),
            )
        ],
    )


NEEDS_REVIEW_CONTENT = content_for("Midterm: 50% Final: 50% Final replaces the makeup exam when higher.")


def overlapping_cutoff_model() -> GradeModel:
    """Otherwise-clean weighted model whose only blocker is an isolated,
    cleanly-resolvable B/C cutoff overlap at 80 (80 should be a B). A is
    kept clear of B so the overlap stays a 2-threshold pair. Every
    threshold carries verbatim evidence text.
    """
    return GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        categories=[
            GradeCategory(name="Midterm", weight=50, evidence=evidence(1, "Midterm: 50%")),
            GradeCategory(name="Final", weight=50, evidence=evidence(1, "Final: 50%")),
        ],
        grade_thresholds=[
            GradeThreshold(letter="A", minimum=91, maximum=100, evidence=evidence(1, "A: 91-100")),
            GradeThreshold(letter="B", minimum=80, maximum=90, evidence=evidence(1, "B: 80-90")),
            GradeThreshold(letter="C", minimum=70, maximum=80, evidence=evidence(1, "C: 70-80")),
        ],
    )


OVERLAPPING_CUTOFF_CONTENT = content_for("Midterm: 50% Final: 50% A: 91-100 B: 80-90 C: 70-80")


def non_adjacent_overlap_model() -> GradeModel:
    """A and C ranges overlap but are not rank-adjacent -- resolve_cutoff_
    overlaps leaves this unresolved, so RESOLVE_CUTOFF_OVERLAP is refused
    and it still blocks.
    """
    return GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        categories=[
            GradeCategory(name="Midterm", weight=50, evidence=evidence(1, "Midterm: 50%")),
            GradeCategory(name="Final", weight=50, evidence=evidence(1, "Final: 50%")),
        ],
        grade_thresholds=[
            GradeThreshold(letter="A", minimum=80, maximum=100, evidence=evidence(1, "A: 80-100")),
            GradeThreshold(letter="C", minimum=70, maximum=85, evidence=evidence(1, "C: 70-85")),
        ],
    )


NON_ADJACENT_OVERLAP_CONTENT = content_for("Midterm: 50% Final: 50% A: 80-100 C: 70-85")


def ingest(client, model, content, *, source_bytes=b"syllabus-bytes", profile_kwargs=None):
    profile = service.get_or_create_profile(
        client,
        student_id=STUDENT_A,
        institution="tamu",
        course_code=(profile_kwargs or {}).get("course_code", "PHYS 207"),
        term="Fall 2026",
    )
    reconciliation = reconcile_grade_model(model, content)
    revision, created = service.ingest_syllabus_extraction(
        client,
        profile_id=profile["id"],
        student_id=STUDENT_A,
        source_bytes=source_bytes,
        source_filename="syllabus.pdf",
        content=content,
        reconciliation=reconciliation,
        parsed_document_schema_version="1",
        extraction_prompt_version="1",
    )
    return profile, revision, created, reconciliation


# --- Test 31: clean accepted model round trip ----------------------------------------


def test_clean_accepted_model_round_trips_and_calculator_ready(client):
    profile, revision, created, reconciliation = ingest(client, clean_model(), CLEAN_CONTENT)
    assert created is True
    assert reconciliation.status == ReconciliationStatus.ACCEPTED

    service.confirm_grade_model(client, revision_id=revision["id"], student_id=STUDENT_A)

    assembled = service.get_syllabus_grade_profile(client, profile_id=profile["id"], student_id=STUDENT_A)
    assert assembled["calculator_ready"] is True
    assert assembled["confirmed_grade_model"] == assembled["extracted_grade_model"]

    result_before = calculate_grade_projection(reconciliation, StudentGradeState(
        category_scores=[
            CategoryScoreInput(category_name="Midterm", actual_score=90),
            CategoryScoreInput(category_name="Final", actual_score=90),
            CategoryScoreInput(category_name="Project", actual_score=90),
        ]
    ))
    result_after = calculate_grade_projection(assembled["reconciliation"], StudentGradeState(
        category_scores=[
            CategoryScoreInput(category_name="Midterm", actual_score=90),
            CategoryScoreInput(category_name="Final", actual_score=90),
            CategoryScoreInput(category_name="Project", actual_score=90),
        ]
    ))
    assert result_before.projected_grade == result_after.projected_grade == 90.0


# --- Test 32: PHYS 207 review workflow ------------------------------------------------


def test_phys_207_with_curve_is_accepted_curve_removal_optional(client):
    # A correctly-extracted curve no longer forces review (syllabus-review
    # redesign §2C / §5): ingest lands ACCEPTED and the student can confirm
    # without removing the curve.
    profile, revision, _, reconciliation = ingest(client, phys_207_with_curve(), PHYS_207_CONTENT)
    assert reconciliation.status == ReconciliationStatus.ACCEPTED

    assembled = service.get_syllabus_grade_profile(client, profile_id=profile["id"], student_id=STUDENT_A)
    assert assembled["calculator_ready"] is False  # not yet confirmed
    assert any(r.rule_type == GradingRuleType.CURVE for r in assembled["extracted_grade_model"].rules)

    confirmed = service.confirm_grade_model(client, revision_id=revision["id"], student_id=STUDENT_A)
    assert confirmed["confirmed_at"] is not None

    final = service.get_syllabus_grade_profile(client, profile_id=profile["id"], student_id=STUDENT_A)
    assert final["calculator_ready"] is True
    # Nothing removed the curve: it is preserved in both the immutable
    # extraction and the confirmed operational model.
    assert any(r.rule_type == GradingRuleType.CURVE for r in final["extracted_grade_model"].rules)
    assert any(r.rule_type == GradingRuleType.CURVE for r in final["confirmed_grade_model"].rules)


def test_curve_removal_via_correction_is_still_available(client):
    # Removing the curve remains a valid path -- it is just no longer
    # required to reach calculator_ready.
    profile, revision, _, _ = ingest(client, phys_207_with_curve(), PHYS_207_CONTENT)
    updated = service.apply_student_corrections(
        client,
        revision_id=revision["id"],
        student_id=STUDENT_A,
        corrections=[
            GradeModelCorrection(target_type=CorrectionTargetType.RULE, operation=CorrectionOperation.REMOVE_RULE, rule_index=0)
        ],
    )
    assert updated["confirmed_reconciliation_status"] == "accepted"

    service.confirm_grade_model(client, revision_id=revision["id"], student_id=STUDENT_A)
    final = service.get_syllabus_grade_profile(client, profile_id=profile["id"], student_id=STUDENT_A)
    assert final["calculator_ready"] is True
    # ORIGINAL extraction keeps the curve; the operational model drops it.
    assert any(r.rule_type == GradingRuleType.CURVE for r in final["extracted_grade_model"].rules)
    assert final["confirmed_grade_model"].rules == []


# --- Test 33: original extraction immutable -------------------------------------------


def test_original_extraction_immutable_after_correction(client):
    profile, revision, _, _ = ingest(client, clean_model(), CLEAN_CONTENT)

    service.apply_student_corrections(
        client,
        revision_id=revision["id"],
        student_id=STUDENT_A,
        corrections=[
            GradeModelCorrection(
                target_type=CorrectionTargetType.CATEGORY,
                operation=CorrectionOperation.SET_WEIGHT,
                category_name="Midterm",
                value=25,
            ),
            GradeModelCorrection(
                target_type=CorrectionTargetType.CATEGORY,
                operation=CorrectionOperation.SET_WEIGHT,
                category_name="Project",
                value=35,
            ),
        ],
    )

    assembled = service.get_syllabus_grade_profile(client, profile_id=profile["id"], student_id=STUDENT_A)
    extracted_midterm = next(c for c in assembled["extracted_grade_model"].categories if c.name == "Midterm")
    confirmed_midterm = next(c for c in assembled["confirmed_grade_model"].categories if c.name == "Midterm")
    assert extracted_midterm.weight == 30
    assert confirmed_midterm.weight == 25
    assert assembled["current_revision"]["corrections"][0]["value"] == 25


# --- Test 34: grade-state round trip --------------------------------------------------


def test_grade_state_round_trip_preserves_actual_vs_projected(client):
    profile, revision, _, _ = ingest(client, phys_207_with_curve(), PHYS_207_CONTENT)
    state = StudentGradeState(
        category_scores=[
            CategoryScoreInput(category_name="Mid-term Exam", actual_score=78),
            CategoryScoreInput(category_name="Final Exam", projected_score=88),
            CategoryScoreInput(category_name="Lecture Quizzes", actual_score=92),
        ]
    )
    service.save_student_grade_state(client, profile_id=profile["id"], student_id=STUDENT_A, grade_state=state)

    assembled = service.get_syllabus_grade_profile(client, profile_id=profile["id"], student_id=STUDENT_A)
    reloaded = assembled["grade_state"]
    by_name = {c.category_name: c for c in reloaded.category_scores}
    assert by_name["Mid-term Exam"].actual_score == 78
    assert by_name["Mid-term Exam"].projected_score is None
    assert by_name["Final Exam"].projected_score == 88
    assert by_name["Final Exam"].actual_score is None
    assert "Recitation Quizzes" not in by_name  # never converted to zero


def test_grade_state_optimistic_concurrency(client):
    profile, revision, _, _ = ingest(client, clean_model(), CLEAN_CONTENT)
    state1 = StudentGradeState(category_scores=[CategoryScoreInput(category_name="Midterm", actual_score=80)])
    row1 = service.save_student_grade_state(client, profile_id=profile["id"], student_id=STUDENT_A, grade_state=state1)
    assert row1["revision"] == 1

    state2 = StudentGradeState(category_scores=[CategoryScoreInput(category_name="Midterm", actual_score=85)])
    row2 = service.save_student_grade_state(
        client, profile_id=profile["id"], student_id=STUDENT_A, grade_state=state2, expected_revision=1
    )
    assert row2["revision"] == 2

    # Stale expected_revision (still 1) must be rejected, not silently overwrite.
    with pytest.raises(GradeStateConflictError):
        service.save_student_grade_state(
            client, profile_id=profile["id"], student_id=STUDENT_A, grade_state=state2, expected_revision=1
        )


# --- Test 35: source revision ----------------------------------------------------------


def test_new_source_does_not_inherit_old_confirmation(client):
    profile, revision_a, _, _ = ingest(client, clean_model(), CLEAN_CONTENT, source_bytes=b"source-a")
    service.confirm_grade_model(client, revision_id=revision_a["id"], student_id=STUDENT_A)

    assembled = service.get_syllabus_grade_profile(client, profile_id=profile["id"], student_id=STUDENT_A)
    assert assembled["profile"]["review_state"] == "confirmed"
    assert assembled["calculator_ready"] is True

    # A materially new source for the SAME profile.
    revised_model = clean_model()
    revised_model.categories[0].weight = 25
    revised_model.categories[2].weight = 35
    new_content = content_for("Midterm: 25% Final: 40% Project: 35% A: 90-100 F: below 60")
    revision_b, created_b = service.ingest_syllabus_extraction(
        client,
        profile_id=profile["id"],
        student_id=STUDENT_A,
        source_bytes=b"source-b",
        source_filename="syllabus_v2.pdf",
        content=new_content,
        reconciliation=reconcile_grade_model(revised_model, new_content),
    )
    assert created_b is True

    reloaded_profile = next(row for row in client.data["syllabus_grade_profiles"] if row["id"] == profile["id"])
    assert reloaded_profile["review_state"] == "reconfirm_required"

    # Old revision A is untouched.
    old_row = next(r for r in client.data["syllabus_grade_revisions"] if r["id"] == revision_a["id"])
    assert old_row["confirmed_at"] is not None
    assert old_row["extracted_grade_model"]["categories"][0]["weight"] == 30


# --- Test 36: idempotent same source ---------------------------------------------------


def test_ingesting_identical_source_twice_is_idempotent(client):
    profile, revision_1, created_1, _ = ingest(client, clean_model(), CLEAN_CONTENT, source_bytes=b"same-bytes")
    profile_2, revision_2, created_2, _ = ingest(client, clean_model(), CLEAN_CONTENT, source_bytes=b"same-bytes")
    assert created_1 is True
    assert created_2 is False
    assert revision_1["id"] == revision_2["id"]
    assert len(client.data["syllabus_grade_revisions"]) == 1


# --- Test 38: invalid correction --------------------------------------------------------


def test_invalid_correction_is_rejected_and_not_partially_applied(client):
    profile, revision, _, _ = ingest(client, clean_model(), CLEAN_CONTENT)
    with pytest.raises(CorrectionApplicationError):
        service.apply_student_corrections(
            client,
            revision_id=revision["id"],
            student_id=STUDENT_A,
            corrections=[
                GradeModelCorrection(
                    target_type=CorrectionTargetType.CATEGORY,
                    operation=CorrectionOperation.SET_WEIGHT,
                    category_name="Midterm",
                    value=10,
                ),
                GradeModelCorrection(
                    target_type=CorrectionTargetType.CATEGORY,
                    operation=CorrectionOperation.SET_WEIGHT,
                    category_name="Nonexistent Category",
                    value=5,
                ),
            ],
        )
    # No revision update was persisted -- the whole correction list failed atomically.
    row = next(r for r in client.data["syllabus_grade_revisions"] if r["id"] == revision["id"])
    assert row["confirmed_grade_model"] is None


def test_negative_weight_correction_rejected(client):
    profile, revision, _, _ = ingest(client, clean_model(), CLEAN_CONTENT)
    with pytest.raises(CorrectionApplicationError):
        service.apply_student_corrections(
            client,
            revision_id=revision["id"],
            student_id=STUDENT_A,
            corrections=[
                GradeModelCorrection(
                    target_type=CorrectionTargetType.CATEGORY,
                    operation=CorrectionOperation.SET_WEIGHT,
                    category_name="Midterm",
                    value=-5,
                )
            ],
        )


def test_invalid_grading_method_correction_rejected(client):
    profile, revision, _, _ = ingest(client, clean_model(), CLEAN_CONTENT)
    with pytest.raises(CorrectionApplicationError):
        service.apply_student_corrections(
            client,
            revision_id=revision["id"],
            student_id=STUDENT_A,
            corrections=[
                GradeModelCorrection(
                    target_type=CorrectionTargetType.GRADING_METHOD,
                    operation=CorrectionOperation.SET_GRADING_METHOD,
                    value="curved",
                )
            ],
        )


# --- Test 39: correction cannot bypass Phase 5 ------------------------------------------


def test_correction_producing_120_percent_stays_needs_review(client):
    profile, revision, _, _ = ingest(client, clean_model(), CLEAN_CONTENT)
    updated = service.apply_student_corrections(
        client,
        revision_id=revision["id"],
        student_id=STUDENT_A,
        corrections=[
            GradeModelCorrection(target_type=CorrectionTargetType.CATEGORY, operation=CorrectionOperation.SET_WEIGHT, category_name="Midterm", value=40),
            GradeModelCorrection(target_type=CorrectionTargetType.CATEGORY, operation=CorrectionOperation.SET_WEIGHT, category_name="Final", value=40),
            GradeModelCorrection(target_type=CorrectionTargetType.CATEGORY, operation=CorrectionOperation.SET_WEIGHT, category_name="Project", value=40),
        ],
    )
    assert updated["confirmed_reconciliation_status"] == "needs_student_review"

    assembled = service.get_syllabus_grade_profile(client, profile_id=profile["id"], student_id=STUDENT_A)
    assert assembled["calculator_ready"] is False

    with pytest.raises(service.GradeModelNotAcceptedError):
        service.confirm_grade_model(client, revision_id=revision["id"], student_id=STUDENT_A)


# --- trust gate: NEEDS_STUDENT_REVIEW still blocks the calculator ----------------------


def test_needs_review_reconciliation_still_blocks_calculator(client):
    profile, revision, _, reconciliation = ingest(client, needs_review_model(), NEEDS_REVIEW_CONTENT)
    assert reconciliation.status == ReconciliationStatus.NEEDS_STUDENT_REVIEW
    with pytest.raises(GradeModelNotReadyError):
        calculate_grade_projection(reconciliation, StudentGradeState())


# --- cutoff-overlap resolution (RESOLVE_CUTOFF_OVERLAP, log-only) -------------------


def _resolve_cutoff(letter: str) -> GradeModelCorrection:
    return GradeModelCorrection(
        target_type=CorrectionTargetType.THRESHOLD,
        operation=CorrectionOperation.RESOLVE_CUTOFF_OVERLAP,
        threshold_letter=letter,
    )


def test_confirming_the_cutoff_default_clears_the_error_and_unblocks_calculator_ready(client):
    profile, revision, _, reconciliation = ingest(client, overlapping_cutoff_model(), OVERLAPPING_CUTOFF_CONTENT)
    assert reconciliation.status == ReconciliationStatus.NEEDS_STUDENT_REVIEW
    assert any(f.code == "overlapping_grade_thresholds" for f in reconciliation.findings)

    updated = service.apply_student_corrections(
        client, revision_id=revision["id"], student_id=STUDENT_A, corrections=[_resolve_cutoff("C")]
    )
    assert updated["confirmed_reconciliation_status"] == "accepted"
    assert updated["clarifying_answers"] == {
        "cutoff_overlap:B,C": {"answer": "confirm_default", "boundary": 80.0, "winner": "B", "loser": "C"}
    }

    service.confirm_grade_model(client, revision_id=revision["id"], student_id=STUDENT_A)
    assembled = service.get_syllabus_grade_profile(client, profile_id=profile["id"], student_id=STUDENT_A)
    assert assembled["calculator_ready"] is True

    # thresholds -- and their verbatim evidence -- are completely unchanged:
    # no narrowing, so no claim_evidence_value_mismatch is ever introduced.
    confirmed = {
        t.letter: (t.minimum, t.maximum, t.evidence.text)
        for t in assembled["confirmed_grade_model"].grade_thresholds
    }
    assert confirmed["C"] == (70, 80, "C: 70-80")
    assert confirmed == {
        t.letter: (t.minimum, t.maximum, t.evidence.text)
        for t in assembled["extracted_grade_model"].grade_thresholds
    }


def test_non_adjacent_overlap_cannot_be_confirmed_away_and_still_blocks(client):
    profile, revision, _, reconciliation = ingest(
        client, non_adjacent_overlap_model(), NON_ADJACENT_OVERLAP_CONTENT
    )
    assert reconciliation.status == ReconciliationStatus.NEEDS_STUDENT_REVIEW

    with pytest.raises(CorrectionApplicationError, match="set_minimum / set_maximum"):
        service.apply_student_corrections(
            client, revision_id=revision["id"], student_id=STUDENT_A, corrections=[_resolve_cutoff("A")]
        )


# --- claim-evidence value confirmation (CONFIRM_THRESHOLD_VALUE, log-only) ----------


def _confirm_threshold_value(letter: str) -> GradeModelCorrection:
    return GradeModelCorrection(
        target_type=CorrectionTargetType.THRESHOLD,
        operation=CorrectionOperation.CONFIRM_THRESHOLD_VALUE,
        threshold_letter=letter,
    )


def ecen_248_confirmed_state_model() -> GradeModel:
    """Mirrors ECEN 248's stored confirmed_grade_model after its cutoff
    overlaps were fixed by manual SET_MAXIMUM/SET_MINIMUM corrections: every
    A-F threshold is now fully bounded, and every one carries verbatim
    ">= / <" comparison-phrasing evidence that _RANGE_RE cannot parse -> all
    five raise claim_evidence_consistency_unverifiable, which is the only
    thing still blocking calculator-ready. Curve / late-work rules and the
    unknown-assessment-count warnings are non-blocking (NON_BLOCKING_
    WARNING_CODES) and must not affect the outcome.
    """
    return GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        categories=[
            GradeCategory(name="Homework", weight=25, count=None, evidence=evidence(1, "Homework 25%")),
            GradeCategory(name="Labs", weight=25, count=None, evidence=evidence(1, "Labs 25%")),
            GradeCategory(name="Midterm Exam", weight=25, evidence=evidence(1, "Midterm Exam 25%")),
            GradeCategory(name="Final Exam", weight=25, evidence=evidence(1, "Final Exam 25%")),
        ],
        grade_thresholds=[
            GradeThreshold(letter="A", minimum=90, maximum=100, evidence=evidence(1, "A: >= 90%")),
            GradeThreshold(letter="B", minimum=80, maximum=89, evidence=evidence(1, "B: >= 80% and < 90%")),
            GradeThreshold(letter="C", minimum=70, maximum=79, evidence=evidence(1, "C: >= 70% and < 80%")),
            GradeThreshold(letter="D", minimum=60, maximum=69, evidence=evidence(1, "D: >= 60% and < 70%")),
            GradeThreshold(letter="F", minimum=0, maximum=59, evidence=evidence(1, "F: < 60%")),
        ],
        rules=[
            GradingRule(
                rule_type=GradingRuleType.CURVE,
                description="Grades will be curved if necessary.",
                evidence=evidence(1, "Grades will be curved if necessary."),
            ),
        ],
        warnings=[
            ExtractionWarning(
                type=ExtractionWarningType.UNKNOWN_ASSESSMENT_COUNT,
                description="The syllabus does not state how many homework assignments there are.",
                related_field="Homework",
            ),
        ],
    )


ECEN_248_CONTENT = content_for(
    "Homework 25% Labs 25% Midterm Exam 25% Final Exam 25% "
    "A: >= 90% B: >= 80% and < 90% C: >= 70% and < 80% D: >= 60% and < 70% F: < 60% "
    "Grades will be curved if necessary."
)


def test_confirming_all_five_a_f_value_claims_clears_ecen_248_and_unblocks_calculator_ready(client):
    """The real-world case this was built for: an ECEN 248-shaped profile
    whose sole remaining blocker is five claim_evidence_consistency_
    unverifiable findings (one per A-F threshold). Affirming all five takes
    the confirmed model to ACCEPTED and, after confirm, calculator-ready --
    with the thresholds and their verbatim evidence completely untouched.
    """
    profile, revision, _, reconciliation = ingest(
        client,
        ecen_248_confirmed_state_model(),
        ECEN_248_CONTENT,
        profile_kwargs={"course_code": "ECEN 248"},
    )
    assert reconciliation.status == ReconciliationStatus.NEEDS_STUDENT_REVIEW
    assert sorted(
        f.field for f in reconciliation.findings if f.code == "claim_evidence_consistency_unverifiable"
    ) == ["threshold:A", "threshold:B", "threshold:C", "threshold:D", "threshold:F"]

    updated = service.apply_student_corrections(
        client,
        revision_id=revision["id"],
        student_id=STUDENT_A,
        corrections=[_confirm_threshold_value(letter) for letter in ("A", "B", "C", "D", "F")],
    )
    assert updated["confirmed_reconciliation_status"] == "accepted"
    assert updated["clarifying_answers"] == {
        f"claim_evidence:threshold:{letter}": {"answer": "confirm_value", "letter": letter}
        for letter in ("a", "b", "c", "d", "f")
    }

    service.confirm_grade_model(client, revision_id=revision["id"], student_id=STUDENT_A)
    assembled = service.get_syllabus_grade_profile(client, profile_id=profile["id"], student_id=STUDENT_A)
    assert assembled["calculator_ready"] is True

    extracted = {
        t.letter: (t.minimum, t.maximum, t.evidence.text)
        for t in assembled["extracted_grade_model"].grade_thresholds
    }
    confirmed = {
        t.letter: (t.minimum, t.maximum, t.evidence.text)
        for t in assembled["confirmed_grade_model"].grade_thresholds
    }
    assert confirmed == extracted
    assert confirmed["A"] == (90, 100, "A: >= 90%")


def test_confirming_only_some_value_claims_still_blocks(client):
    profile, revision, _, _ = ingest(
        client,
        ecen_248_confirmed_state_model(),
        ECEN_248_CONTENT,
        profile_kwargs={"course_code": "ECEN 248"},
    )
    updated = service.apply_student_corrections(
        client,
        revision_id=revision["id"],
        student_id=STUDENT_A,
        corrections=[_confirm_threshold_value(letter) for letter in ("B", "C", "D")],
    )
    assert updated["confirmed_reconciliation_status"] == "needs_student_review"
    with pytest.raises(service.GradeModelNotAcceptedError):
        service.confirm_grade_model(client, revision_id=revision["id"], student_id=STUDENT_A)


def test_confirm_threshold_value_for_a_clean_threshold_is_rejected(client):
    _, revision, _, _ = ingest(client, clean_model(), CLEAN_CONTENT)
    with pytest.raises(CorrectionApplicationError, match="no unverified value claim"):
        service.apply_student_corrections(
            client,
            revision_id=revision["id"],
            student_id=STUDENT_A,
            corrections=[_confirm_threshold_value("A")],
        )
