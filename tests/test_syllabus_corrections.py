import pytest

from GradusIQ_career.syllabus.corrections import (
    CorrectionApplicationError,
    CorrectionOperation,
    CorrectionTargetType,
    GradeModelCorrection,
    apply_grade_model_corrections,
)
from GradusIQ_career.syllabus.models import (
    Assessment,
    GradeCategory,
    GradeModel,
    GradeThreshold,
    GradingMethod,
    GradingRule,
    GradingRuleType,
    SourceEvidence,
)


def correction(target_type, operation, **kwargs) -> GradeModelCorrection:
    return GradeModelCorrection(target_type=target_type, operation=operation, **kwargs)


# --- category corrections -------------------------------------------------------------


def test_rename_category():
    model = GradeModel(categories=[GradeCategory(name="Midterm", weight=35)])
    result = apply_grade_model_corrections(
        model, [correction(CorrectionTargetType.CATEGORY, CorrectionOperation.RENAME, category_name="Midterm", value="Mid-term Exam")]
    )
    assert result.categories[0].name == "Mid-term Exam"
    assert model.categories[0].name == "Midterm"  # original untouched


def test_set_category_count():
    model = GradeModel(categories=[GradeCategory(name="Quizzes", weight=5, count=None)])
    result = apply_grade_model_corrections(
        model, [correction(CorrectionTargetType.CATEGORY, CorrectionOperation.SET_COUNT, category_name="Quizzes", value=8)]
    )
    assert result.categories[0].count == 8
    assert model.categories[0].count is None


def test_unknown_category_rejected():
    model = GradeModel(categories=[GradeCategory(name="Midterm", weight=35)])
    with pytest.raises(CorrectionApplicationError):
        apply_grade_model_corrections(
            model, [correction(CorrectionTargetType.CATEGORY, CorrectionOperation.SET_WEIGHT, category_name="Ghost", value=10)]
        )


# --- assessment corrections -------------------------------------------------------------


def test_set_assessment_points_and_date():
    model = GradeModel(
        grading_method=GradingMethod.POINTS,
        assessments=[Assessment(name="Final", points=None, date=None)],
    )
    result = apply_grade_model_corrections(
        model,
        [
            correction(CorrectionTargetType.ASSESSMENT, CorrectionOperation.SET_POINTS, assessment_name="Final", value=300),
            correction(CorrectionTargetType.ASSESSMENT, CorrectionOperation.SET_DATE, assessment_name="Final", value="December 10"),
        ],
    )
    assert result.assessments[0].points == 300
    assert result.assessments[0].date == "December 10"


def test_set_category_reference_requires_existing_category():
    model = GradeModel(
        categories=[GradeCategory(name="Quizzes", weight=20)],
        assessments=[Assessment(name="Quiz 1")],
    )
    with pytest.raises(CorrectionApplicationError):
        apply_grade_model_corrections(
            model,
            [
                correction(
                    CorrectionTargetType.ASSESSMENT,
                    CorrectionOperation.SET_CATEGORY_REFERENCE,
                    assessment_name="Quiz 1",
                    value="Nonexistent Category",
                )
            ],
        )


def test_set_category_reference_to_existing_category_succeeds():
    model = GradeModel(
        categories=[GradeCategory(name="Quizzes", weight=20)],
        assessments=[Assessment(name="Quiz 1")],
    )
    result = apply_grade_model_corrections(
        model,
        [
            correction(
                CorrectionTargetType.ASSESSMENT,
                CorrectionOperation.SET_CATEGORY_REFERENCE,
                assessment_name="Quiz 1",
                value="Quizzes",
            )
        ],
    )
    assert result.assessments[0].category == "Quizzes"


def test_clear_dangling_category_reference():
    model = GradeModel(assessments=[Assessment(name="Quiz 1", category="Some Category That Does Not Exist")])
    result = apply_grade_model_corrections(
        model,
        [correction(CorrectionTargetType.ASSESSMENT, CorrectionOperation.CLEAR_CATEGORY_REFERENCE, assessment_name="Quiz 1")],
    )
    assert result.assessments[0].category is None


# --- threshold corrections --------------------------------------------------------------


def test_set_threshold_minimum_and_maximum():
    model = GradeModel(grade_thresholds=[GradeThreshold(letter="A", minimum=85, maximum=100)])
    result = apply_grade_model_corrections(
        model,
        [
            correction(CorrectionTargetType.THRESHOLD, CorrectionOperation.SET_MINIMUM, threshold_letter="A", value=90),
        ],
    )
    assert result.grade_thresholds[0].minimum == 90
    assert result.grade_thresholds[0].maximum == 100


def test_threshold_correction_rejects_inverted_bounds():
    model = GradeModel(grade_thresholds=[GradeThreshold(letter="A", minimum=90, maximum=100)])
    with pytest.raises(CorrectionApplicationError):
        apply_grade_model_corrections(
            model,
            [correction(CorrectionTargetType.THRESHOLD, CorrectionOperation.SET_MINIMUM, threshold_letter="A", value=101)],
        )


def test_unknown_threshold_letter_rejected():
    model = GradeModel(grade_thresholds=[GradeThreshold(letter="A", minimum=90, maximum=100)])
    with pytest.raises(CorrectionApplicationError):
        apply_grade_model_corrections(
            model,
            [correction(CorrectionTargetType.THRESHOLD, CorrectionOperation.SET_MINIMUM, threshold_letter="Z", value=90)],
        )


# --- resolve_cutoff_overlap: a validated no-op on the model --------------------------------


def _bc_overlap_model() -> GradeModel:
    # Isolated, cleanly-resolvable B/C overlap at 80 (A kept clear of B), with
    # verbatim evidence text on every threshold.
    def ev(text):
        return SourceEvidence(page=1, text=text, confidence=1.0)

    return GradeModel(
        grade_thresholds=[
            GradeThreshold(letter="A", minimum=91, maximum=100, evidence=ev("A: 91-100")),
            GradeThreshold(letter="B", minimum=80, maximum=90, evidence=ev("B: 80-90")),
            GradeThreshold(letter="C", minimum=70, maximum=80, evidence=ev("C: 70-80")),
        ],
    )


def _resolve(letter):
    return correction(
        CorrectionTargetType.THRESHOLD, CorrectionOperation.RESOLVE_CUTOFF_OVERLAP, threshold_letter=letter
    )


def test_resolve_cutoff_overlap_leaves_the_model_completely_unchanged():
    model = _bc_overlap_model()
    result = apply_grade_model_corrections(model, [_resolve("C")])
    assert result.model_dump() == model.model_dump()
    # in particular the loser's range and its verbatim evidence are untouched
    c = next(t for t in result.grade_thresholds if t.letter == "C")
    assert (c.minimum, c.maximum, c.evidence.text) == (70, 80, "C: 70-80")


def test_resolve_cutoff_overlap_accepts_either_letter_of_the_pair():
    assert apply_grade_model_corrections(_bc_overlap_model(), [_resolve("B")]).model_dump() == _bc_overlap_model().model_dump()
    assert apply_grade_model_corrections(_bc_overlap_model(), [_resolve("C")]).model_dump() == _bc_overlap_model().model_dump()


def test_resolve_cutoff_overlap_rejects_a_non_adjacent_overlap():
    model = GradeModel(
        grade_thresholds=[
            GradeThreshold(letter="A", minimum=80, maximum=100),
            GradeThreshold(letter="C", minimum=70, maximum=85),
        ],
    )
    with pytest.raises(CorrectionApplicationError, match="set_minimum / set_maximum"):
        apply_grade_model_corrections(model, [_resolve("A")])


def test_resolve_cutoff_overlap_rejects_a_multi_way_overlap():
    model = GradeModel(
        grade_thresholds=[
            GradeThreshold(letter="A", minimum=90, maximum=100),
            GradeThreshold(letter="B", minimum=80, maximum=90),
            GradeThreshold(letter="C", minimum=70, maximum=80),
        ],
    )
    with pytest.raises(CorrectionApplicationError, match="no cleanly resolvable cutoff overlap"):
        apply_grade_model_corrections(model, [_resolve("B")])


def test_resolve_cutoff_overlap_with_no_overlap_present_is_rejected():
    model = GradeModel(
        grade_thresholds=[
            GradeThreshold(letter="A", minimum=90, maximum=100),
            GradeThreshold(letter="B", minimum=80, maximum=89),
        ],
    )
    with pytest.raises(CorrectionApplicationError, match="no cleanly resolvable cutoff overlap"):
        apply_grade_model_corrections(model, [_resolve("A")])


# --- confirm_threshold_value: a validated no-op on the model ------------------------------


def ev(text):
    return SourceEvidence(page=1, text=text, confidence=1.0)


def _unverifiable_threshold_model() -> GradeModel:
    # B's evidence uses ">= / <" phrasing _RANGE_RE cannot parse -> B yields
    # claim_evidence_consistency_unverifiable. C's evidence range (70-80)
    # disagrees with its narrowed bounds (70-79) -> claim_evidence_value_
    # mismatch. A verifies clean. F is single-bound (range check skips it).
    return GradeModel(
        grade_thresholds=[
            GradeThreshold(letter="A", minimum=90, maximum=100, evidence=ev("A: 90-100")),
            GradeThreshold(letter="B", minimum=80, maximum=89, evidence=ev("B: >= 80% and < 90%")),
            GradeThreshold(letter="C", minimum=70, maximum=79, evidence=ev("C: 70-80")),
            GradeThreshold(letter="F", maximum=59, evidence=ev("F: < 60%")),
        ],
    )


def _confirm_value(letter):
    return correction(
        CorrectionTargetType.THRESHOLD, CorrectionOperation.CONFIRM_THRESHOLD_VALUE, threshold_letter=letter
    )


def test_confirm_threshold_value_leaves_the_model_completely_unchanged():
    model = _unverifiable_threshold_model()
    result = apply_grade_model_corrections(model, [_confirm_value("B")])
    assert result.model_dump() == model.model_dump()


def test_confirm_threshold_value_accepts_an_unverifiable_claim():
    model = _unverifiable_threshold_model()
    assert apply_grade_model_corrections(model, [_confirm_value("B")]).model_dump() == model.model_dump()


def test_confirm_threshold_value_accepts_a_value_mismatch_claim():
    model = _unverifiable_threshold_model()
    assert apply_grade_model_corrections(model, [_confirm_value("C")]).model_dump() == model.model_dump()


def test_confirm_threshold_value_is_case_insensitive_on_the_letter():
    model = _unverifiable_threshold_model()
    assert apply_grade_model_corrections(model, [_confirm_value("b")]).model_dump() == model.model_dump()


def test_confirm_threshold_value_noops_on_a_threshold_that_verifies_clean():
    # A verifies clean against its evidence -> no finding to suppress. The
    # affirmation is inert (confirmed_value_claims has nothing to match), so
    # it is tolerated as a no-op rather than raising: the unified cutoff
    # table auto-appends CONFIRM_THRESHOLD_VALUE after every edit and must
    # not blow up the atomic batch when the edited value needs no affirming.
    model = _unverifiable_threshold_model()
    assert apply_grade_model_corrections(model, [_confirm_value("A")]).model_dump() == model.model_dump()


def test_confirm_threshold_value_noops_on_a_single_bound_threshold():
    # The range check never runs on a single-bound threshold, so there is no
    # claim_evidence finding to affirm -- tolerated as a no-op.
    model = _unverifiable_threshold_model()
    assert apply_grade_model_corrections(model, [_confirm_value("F")]).model_dump() == model.model_dump()


def test_confirm_threshold_value_rejects_an_unknown_letter():
    # A missing threshold is still a real mistake -- only "nothing to
    # confirm" is tolerated, not "no such threshold".
    model = _unverifiable_threshold_model()
    with pytest.raises(CorrectionApplicationError, match="unknown threshold letter"):
        apply_grade_model_corrections(model, [_confirm_value("Z")])


# --- set_minimum/set_maximum + auto-appended confirm_threshold_value -------------------
# The unified cutoff table submits, for every letter it edited in place, a
# SET_MINIMUM / SET_MAXIMUM followed by a CONFIRM_THRESHOLD_VALUE for the
# same letter in one atomic batch, so the student is never re-prompted to
# affirm a value they just typed. The confirmation must never fail that
# batch, whatever the edit left behind.


def _set_max(letter, value):
    return correction(
        CorrectionTargetType.THRESHOLD, CorrectionOperation.SET_MAXIMUM, threshold_letter=letter, value=value
    )


def _edit_batch_model() -> GradeModel:
    return GradeModel(
        grade_thresholds=[
            # edit 89 -> 90 makes B match its cited "B: 80-90" exactly: no residual finding
            GradeThreshold(letter="B", minimum=80, maximum=89, evidence=ev("B: 80-90")),
            # edit 80 -> 79 keeps C disagreeing with its cited "C: 70-80": residual finding
            GradeThreshold(letter="C", minimum=70, maximum=80, evidence=ev("C: 70-80")),
            # no citable evidence text at all: range check returns early, no finding
            GradeThreshold(letter="D", minimum=60, maximum=69, evidence=None),
            # single-bound: range check skips it, no finding
            GradeThreshold(letter="F", maximum=59, evidence=ev("F: < 60%")),
        ],
    )


def test_edit_then_autoaffirm_batch_edit_matches_evidence():
    model = _edit_batch_model()
    result = apply_grade_model_corrections(model, [_set_max("B", 90), _confirm_value("B")])
    assert result.grade_thresholds[0].maximum == 90
    assert model.grade_thresholds[0].maximum == 89  # original untouched


def test_edit_then_autoaffirm_batch_edit_still_mismatches_evidence():
    model = _edit_batch_model()
    result = apply_grade_model_corrections(model, [_set_max("C", 79), _confirm_value("C")])
    assert result.grade_thresholds[1].maximum == 79


def test_edit_then_autoaffirm_batch_threshold_has_no_evidence_text():
    model = _edit_batch_model()
    result = apply_grade_model_corrections(model, [_set_max("D", 68), _confirm_value("D")])
    assert result.grade_thresholds[2].maximum == 68


def test_edit_then_autoaffirm_batch_single_bound_threshold():
    model = _edit_batch_model()
    result = apply_grade_model_corrections(model, [_set_max("F", 58), _confirm_value("F")])
    assert result.grade_thresholds[3].maximum == 58


def test_edit_then_autoaffirm_all_four_scenarios_in_one_atomic_batch():
    # Every edit + its auto-appended affirmation, together: the batch that
    # would previously have aborted on the first affirm with nothing to
    # confirm now applies cleanly end to end.
    model = _edit_batch_model()
    result = apply_grade_model_corrections(
        model,
        [
            _set_max("B", 90), _confirm_value("B"),
            _set_max("C", 79), _confirm_value("C"),
            _set_max("D", 68), _confirm_value("D"),
            _set_max("F", 58), _confirm_value("F"),
        ],
    )
    assert [t.maximum for t in result.grade_thresholds] == [90, 79, 68, 58]


# --- rule corrections ----------------------------------------------------------------------


def test_set_rule_source_and_target():
    model = GradeModel(
        categories=[GradeCategory(name="Final Exam", weight=50), GradeCategory(name="Mid-term Exam", weight=35)],
        rules=[GradingRule(rule_type=GradingRuleType.REPLACEMENT, description="The final may replace another test.")],
    )
    result = apply_grade_model_corrections(
        model,
        [
            correction(CorrectionTargetType.RULE, CorrectionOperation.SET_SOURCE, rule_index=0, value="Final Exam"),
            correction(CorrectionTargetType.RULE, CorrectionOperation.SET_TARGET, rule_index=0, value="Mid-term Exam"),
            correction(
                CorrectionTargetType.RULE,
                CorrectionOperation.SET_CONDITION,
                rule_index=0,
                value="final_score > midterm_score",
            ),
        ],
    )
    assert result.rules[0].source == "Final Exam"
    assert result.rules[0].target == "Mid-term Exam"
    assert result.rules[0].condition == "final_score > midterm_score"


def test_remove_rule():
    model = GradeModel(rules=[GradingRule(rule_type=GradingRuleType.CURVE, description="May be curved.")])
    result = apply_grade_model_corrections(
        model, [correction(CorrectionTargetType.RULE, CorrectionOperation.REMOVE_RULE, rule_index=0)]
    )
    assert result.rules == []
    assert len(model.rules) == 1  # original untouched


def test_confirm_rule_is_a_no_op_on_the_model():
    model = GradeModel(rules=[GradingRule(rule_type=GradingRuleType.CURVE, description="May be curved.")])
    result = apply_grade_model_corrections(
        model, [correction(CorrectionTargetType.RULE, CorrectionOperation.CONFIRM_RULE, rule_index=0)]
    )
    assert result.rules[0].description == "May be curved."


def test_unknown_rule_index_rejected():
    model = GradeModel(rules=[GradingRule(rule_type=GradingRuleType.CURVE, description="May be curved.")])
    with pytest.raises(CorrectionApplicationError):
        apply_grade_model_corrections(
            model, [correction(CorrectionTargetType.RULE, CorrectionOperation.REMOVE_RULE, rule_index=5)]
        )


# --- grading method correction ----------------------------------------------------------


def test_set_grading_method():
    model = GradeModel(grading_method=GradingMethod.UNKNOWN)
    result = apply_grade_model_corrections(
        model, [correction(CorrectionTargetType.GRADING_METHOD, CorrectionOperation.SET_GRADING_METHOD, value="weighted")]
    )
    assert result.grading_method == GradingMethod.WEIGHTED


def test_invalid_grading_method_value_rejected():
    model = GradeModel(grading_method=GradingMethod.UNKNOWN)
    with pytest.raises(CorrectionApplicationError):
        apply_grade_model_corrections(
            model, [correction(CorrectionTargetType.GRADING_METHOD, CorrectionOperation.SET_GRADING_METHOD, value="curved")]
        )


# --- atomicity ------------------------------------------------------------------------------


def test_corrections_apply_atomically_not_partially():
    model = GradeModel(categories=[GradeCategory(name="Midterm", weight=35), GradeCategory(name="Final", weight=50)])
    with pytest.raises(CorrectionApplicationError):
        apply_grade_model_corrections(
            model,
            [
                correction(CorrectionTargetType.CATEGORY, CorrectionOperation.SET_WEIGHT, category_name="Midterm", value=30),
                correction(CorrectionTargetType.CATEGORY, CorrectionOperation.SET_WEIGHT, category_name="Final", value=-1),
            ],
        )
    # The model itself is never mutated regardless of success/failure.
    assert model.categories[0].weight == 35
    assert model.categories[1].weight == 50


def test_evidence_is_never_a_correctable_field():
    """Correction operations never touch evidence -- see corrections.py
    module docstring on the extracted-vs-confirmed provenance boundary.
    """
    from GradusIQ_career.syllabus.corrections import CorrectionOperation as Op

    weight_related_ops = {Op.RENAME, Op.SET_WEIGHT, Op.SET_COUNT}
    assert "evidence" not in {op.value for op in weight_related_ops}
    # No CorrectionOperation member references evidence at all.
    assert not any("evidence" in op.value for op in Op)
