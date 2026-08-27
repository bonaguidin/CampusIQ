import pytest

from GradusIQ_career.syllabus.calculator import (
    AssessmentScoreInput,
    CategoryScoreInput,
    GradeCalculationError,
    GradeInputValidationError,
    GradeModelNotReadyError,
    GradeModelStructureError,
    ScoreStatus,
    StudentGradeState,
    TargetScoreResult,
    UnsupportedGradingMethodError,
    UnsupportedGradingStructureError,
    UnsupportedRuleConditionError,
    calculate_grade_projection,
    solve_required_score,
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
from GradusIQ_career.syllabus.reconciliation import (
    GradeModelReconciliationResult,
    ReconciliationStatus,
    reconcile_grade_model,
)
from GradusIQ_career.syllabus.relevance import RelevantPage, RelevantSyllabusContent


def evidence(page_number: int, text: str) -> SourceEvidence:
    return SourceEvidence(page=page_number, text=text, confidence=1.0)


def content_for(*texts: str) -> RelevantSyllabusContent:
    pages = [RelevantPage(page_number=i + 1, markdown=text, relevance_score=5.0) for i, text in enumerate(texts)]
    combined = "\n\n".join(f"<!-- page: {p.page_number} -->\n\n{p.markdown}" for p in pages)
    return RelevantSyllabusContent(
        selected_pages=pages, selected_sections=[], markdown=combined, source_page_count=len(pages), selected_page_count=len(pages)
    )


def accepted(grade_model: GradeModel, content: RelevantSyllabusContent) -> GradeModelReconciliationResult:
    result = reconcile_grade_model(grade_model, content)
    assert result.status == ReconciliationStatus.ACCEPTED, result.findings
    return result


def needs_review(grade_model: GradeModel, content: RelevantSyllabusContent) -> GradeModelReconciliationResult:
    result = reconcile_grade_model(grade_model, content)
    assert result.status == ReconciliationStatus.NEEDS_STUDENT_REVIEW
    return result


PHYS_207_MARKDOWN = (
    "Mid-term Exam: 35% Final Exam: 50% Lecture Quizzes: 5% Recitation Quizzes: 10% "
    "Final replaces Midterm when final is higher."
)


def phys_207_model(*, with_replacement: bool = True) -> GradeModel:
    rules = []
    if with_replacement:
        rules.append(
            GradingRule(
                rule_type=GradingRuleType.REPLACEMENT,
                description="Final replaces Midterm when final is higher.",
                source="Final Exam",
                target="Mid-term Exam",
                condition="final_score > midterm_score",
                evidence=evidence(1, "Final replaces Midterm when final is higher."),
            )
        )
    return GradeModel(
        grading_method=GradingMethod.WEIGHTED,
        categories=[
            GradeCategory(name="Mid-term Exam", weight=35, evidence=evidence(1, "Mid-term Exam: 35%")),
            GradeCategory(name="Final Exam", weight=50, evidence=evidence(1, "Final Exam: 50%")),
            GradeCategory(name="Lecture Quizzes", weight=5, evidence=evidence(1, "Lecture Quizzes: 5%")),
            GradeCategory(name="Recitation Quizzes", weight=10, evidence=evidence(1, "Recitation Quizzes: 10%")),
        ],
        rules=rules,
    )


PHYS_207_CONTENT = content_for(PHYS_207_MARKDOWN)


def phys_207_state() -> StudentGradeState:
    return StudentGradeState(
        category_scores=[
            CategoryScoreInput(category_name="Mid-term Exam", actual_score=78),
            CategoryScoreInput(category_name="Lecture Quizzes", actual_score=92),
            CategoryScoreInput(category_name="Recitation Quizzes", actual_score=88),
        ]
    )


# --- trust gate (section 38) --------------------------------------------------------


def test_accepted_reconciliation_can_calculate():
    recon = accepted(phys_207_model(with_replacement=False), PHYS_207_CONTENT)
    result = calculate_grade_projection(recon, phys_207_state())
    assert result.current_grade == 81.4


def test_needs_review_cannot_calculate():
    model = phys_207_model(with_replacement=False)
    model.rules.append(GradingRule(rule_type=GradingRuleType.CURVE, description="May be curved."))
    recon = needs_review(model, PHYS_207_CONTENT)
    with pytest.raises(GradeModelNotReadyError):
        calculate_grade_projection(recon, phys_207_state())


def test_needs_review_cannot_solve():
    model = phys_207_model(with_replacement=False)
    model.rules.append(GradingRule(rule_type=GradingRuleType.CURVE, description="May be curved."))
    recon = needs_review(model, PHYS_207_CONTENT)
    with pytest.raises(GradeModelNotReadyError):
        solve_required_score(recon, phys_207_state(), target_component="Final Exam", target_grade=90)


def test_calculator_reads_reconciliation_grade_model_not_caller_copy():
    recon = accepted(phys_207_model(with_replacement=False), PHYS_207_CONTENT)
    # recon.grade_model is a deep copy per Phase 5; calculation still works from it.
    result = calculate_grade_projection(recon, phys_207_state())
    assert result.grading_method == GradingMethod.WEIGHTED


def test_no_bare_grademodel_public_entry_point():
    import inspect

    from GradusIQ_career.syllabus.calculator import engine, solver

    calc_sig = inspect.signature(engine.calculate_grade_projection)
    solve_sig = inspect.signature(solver.solve_required_score)
    assert list(calc_sig.parameters)[0] == "reconciliation"
    assert list(solve_sig.parameters)[0] == "reconciliation"
    assert calc_sig.parameters["reconciliation"].annotation.__name__ == "GradeModelReconciliationResult"


# --- weighted calculation (section 39) -----------------------------------------------


def test_phys_207_current_grade_before_final():
    recon = accepted(phys_207_model(with_replacement=False), PHYS_207_CONTENT)
    result = calculate_grade_projection(recon, phys_207_state())
    assert result.completed_weight == 50.0
    assert result.earned_course_percentage == 40.7
    assert result.current_grade == 81.4
    assert result.projected_grade is None


def test_complete_weighted_course_produces_projected_grade():
    recon = accepted(phys_207_model(with_replacement=False), PHYS_207_CONTENT)
    state = phys_207_state()
    state.category_scores.append(CategoryScoreInput(category_name="Final Exam", actual_score=80))
    result = calculate_grade_projection(recon, state)
    expected = 78 * 0.35 + 80 * 0.50 + 92 * 0.05 + 88 * 0.10
    assert result.projected_grade == round(expected, 2)
    assert result.current_grade == round(expected, 2)  # everything completed -> current == projected


def test_partially_completed_course_has_current_but_no_projected():
    recon = accepted(phys_207_model(with_replacement=False), PHYS_207_CONTENT)
    result = calculate_grade_projection(recon, phys_207_state())
    assert result.current_grade is not None
    assert result.projected_grade is None


def test_projected_score_produces_projected_grade_only():
    recon = accepted(phys_207_model(with_replacement=False), PHYS_207_CONTENT)
    state = phys_207_state()
    state.category_scores.append(CategoryScoreInput(category_name="Final Exam", projected_score=85))
    result = calculate_grade_projection(recon, state)
    assert result.projected_grade is not None
    final_component = next(c for c in result.components if c.name == "Final Exam")
    assert final_component.status == ScoreStatus.PROJECTED
    assert final_component.original_score == 85


def test_zero_score_is_valid():
    recon = accepted(phys_207_model(with_replacement=False), PHYS_207_CONTENT)
    state = StudentGradeState(category_scores=[CategoryScoreInput(category_name="Mid-term Exam", actual_score=0)])
    result = calculate_grade_projection(recon, state)
    assert result.current_grade == 0.0


def test_hundred_score_is_valid():
    recon = accepted(phys_207_model(with_replacement=False), PHYS_207_CONTENT)
    state = StudentGradeState(category_scores=[CategoryScoreInput(category_name="Mid-term Exam", actual_score=100)])
    result = calculate_grade_projection(recon, state)
    assert result.current_grade == 100.0


def test_invalid_score_rejected():
    with pytest.raises(Exception):
        CategoryScoreInput(category_name="Mid-term Exam", actual_score=150)


def test_missing_score_is_not_treated_as_zero():
    recon = accepted(phys_207_model(with_replacement=False), PHYS_207_CONTENT)
    state = StudentGradeState(category_scores=[CategoryScoreInput(category_name="Mid-term Exam", actual_score=78)])
    result = calculate_grade_projection(recon, state)
    # only midterm (35%) is completed -- current grade normalizes to 78, not
    # deflated by treating the other 65% as zero.
    assert result.current_grade == 78.0
    assert result.completed_weight == 35.0


def test_unknown_category_input_rejected():
    recon = accepted(phys_207_model(with_replacement=False), PHYS_207_CONTENT)
    state = StudentGradeState(category_scores=[CategoryScoreInput(category_name="Nonexistent", actual_score=50)])
    with pytest.raises(GradeInputValidationError):
        calculate_grade_projection(recon, state)


def test_duplicate_category_input_rejected():
    # Two normalized-equal category names supplied together must be
    # rejected by the engine, even though StudentGradeState itself places
    # no uniqueness constraint on the list.
    state = StudentGradeState(
        category_scores=[
            CategoryScoreInput(category_name="Mid-term Exam", actual_score=50),
            CategoryScoreInput(category_name="mid-term   exam", actual_score=60),
        ]
    )
    recon = accepted(phys_207_model(with_replacement=False), PHYS_207_CONTENT)
    with pytest.raises(GradeInputValidationError):
        calculate_grade_projection(recon, state)


# --- points calculation (section 40) -------------------------------------------------


def points_model() -> GradeModel:
    return GradeModel(
        grading_method=GradingMethod.POINTS,
        assessments=[
            Assessment(name="Midterm", points=200, evidence=evidence(1, "Midterm: 200 points")),
            Assessment(name="Final", points=300, evidence=evidence(1, "Final: 300 points")),
            Assessment(name="Homework", points=500, evidence=evidence(1, "Homework: 500 points")),
        ],
    )


POINTS_CONTENT = content_for("Midterm: 200 points Final: 300 points Homework: 500 points")


def test_points_earned_possible_calculation():
    recon = accepted(points_model(), POINTS_CONTENT)
    state = StudentGradeState(
        assessment_scores=[
            AssessmentScoreInput(assessment_name="Midterm", earned_points=180, points_status=ScoreStatus.COMPLETED),
            AssessmentScoreInput(assessment_name="Homework", earned_points=450, points_status=ScoreStatus.COMPLETED),
        ]
    )
    result = calculate_grade_projection(recon, state)
    expected_current = (180 + 450) / (200 + 500) * 100
    assert result.current_grade == round(expected_current, 2)


def test_partial_points_course_has_no_projected_grade():
    recon = accepted(points_model(), POINTS_CONTENT)
    state = StudentGradeState(
        assessment_scores=[
            AssessmentScoreInput(assessment_name="Midterm", earned_points=180, points_status=ScoreStatus.COMPLETED),
        ]
    )
    result = calculate_grade_projection(recon, state)
    assert result.projected_grade is None
    assert result.current_grade is not None


def test_projected_remaining_points_assessment():
    recon = accepted(points_model(), POINTS_CONTENT)
    state = StudentGradeState(
        assessment_scores=[
            AssessmentScoreInput(assessment_name="Midterm", earned_points=180, points_status=ScoreStatus.COMPLETED),
            AssessmentScoreInput(assessment_name="Homework", earned_points=450, points_status=ScoreStatus.COMPLETED),
            AssessmentScoreInput(assessment_name="Final", earned_points=250, points_status=ScoreStatus.PROJECTED),
        ]
    )
    result = calculate_grade_projection(recon, state)
    expected = (180 + 450 + 250) / (200 + 500 + 300) * 100
    assert result.projected_grade == round(expected, 2)
    final_component = next(c for c in result.components if c.name == "Final")
    assert final_component.status == ScoreStatus.PROJECTED


def test_zero_possible_points_handled_safely():
    # A single zero-possible-points assessment has no usable share of the
    # course; the calculation must not crash (e.g. divide by zero) -- it
    # simply cannot resolve a grade from it.
    model = GradeModel(
        grading_method=GradingMethod.POINTS,
        assessments=[Assessment(name="Bonus", points=0, evidence=evidence(1, "Bonus: 0 points"))],
    )
    content = content_for("Bonus: 0 points")
    recon = accepted(model, content)
    result = calculate_grade_projection(recon, StudentGradeState())
    assert result.current_grade is None
    assert result.projected_grade is None


def test_insufficient_point_metadata_excludes_assessment_with_warning():
    model = GradeModel(
        grading_method=GradingMethod.POINTS,
        assessments=[
            Assessment(name="Midterm", points=200, evidence=evidence(1, "Midterm: 200 points")),
            Assessment(name="Mystery", points=None),
        ],
    )
    content = content_for("Midterm: 200 points")
    recon = accepted(model, content)
    result = calculate_grade_projection(recon, StudentGradeState())
    assert any("Mystery" in w for w in result.warnings)
    assert all(c.name != "Mystery" for c in result.components)


# --- target solver (section 41) --------------------------------------------------------


def test_solve_one_remaining_unknown():
    recon = accepted(phys_207_model(with_replacement=False), PHYS_207_CONTENT)
    result = solve_required_score(recon, phys_207_state(), target_component="Final Exam", target_grade=85)
    expected = (85 - (78 * 0.35 + 92 * 0.05 + 88 * 0.10)) / 0.50
    assert result.required_score == round(expected, 2)
    assert result.feasible is True


def test_target_already_achieved():
    # Completed contribution alone (78*.35 + 92*.05 + 88*.10 = 40.7) already
    # covers a target of 30 regardless of the Final's score.
    recon = accepted(phys_207_model(with_replacement=False), PHYS_207_CONTENT)
    result = solve_required_score(recon, phys_207_state(), target_component="Final Exam", target_grade=30)
    assert result.already_achieved is True
    assert result.feasible is True
    assert result.required_score <= 0


def test_impossible_target_over_100_required():
    recon = accepted(phys_207_model(with_replacement=False), PHYS_207_CONTENT)
    result = solve_required_score(recon, phys_207_state(), target_component="Final Exam", target_grade=99.9)
    assert result.feasible is False
    assert result.required_score > 100


def test_unresolved_additional_unknown_prevents_solving():
    recon = accepted(phys_207_model(with_replacement=False), PHYS_207_CONTENT)
    state = StudentGradeState(category_scores=[CategoryScoreInput(category_name="Mid-term Exam", actual_score=78)])
    result = solve_required_score(recon, state, target_component="Final Exam", target_grade=90)
    assert result.required_score is None
    assert result.feasible is False
    assert any("Lecture Quizzes" in w or "Recitation Quizzes" in w for w in result.warnings)


def test_letter_target_resolves_from_threshold():
    model = phys_207_model(with_replacement=False)
    model.grade_thresholds = [
        GradeThreshold(letter="A", minimum=90, maximum=100, evidence=evidence(1, "A: 90-100")),
        GradeThreshold(letter="B", minimum=80, maximum=89, evidence=evidence(1, "B: 80-89")),
    ]
    content = content_for(PHYS_207_MARKDOWN + " A: 90-100 B: 80-89")
    recon = accepted(model, content)
    result = solve_required_score(recon, phys_207_state(), target_component="Final Exam", target_letter="A")
    assert result.target_grade == 90
    assert result.target_label == "A"


def test_unknown_letter_target_rejected():
    recon = accepted(phys_207_model(with_replacement=False), PHYS_207_CONTENT)
    with pytest.raises(GradeInputValidationError):
        solve_required_score(recon, phys_207_state(), target_component="Final Exam", target_letter="Z")


def test_threshold_without_usable_minimum_rejected():
    model = phys_207_model(with_replacement=False)
    model.grade_thresholds = [GradeThreshold(letter="F", maximum=44, evidence=evidence(1, "F: below 45"))]
    content = content_for(PHYS_207_MARKDOWN + " F: below 45")
    recon = accepted(model, content)
    with pytest.raises(GradeInputValidationError):
        solve_required_score(recon, phys_207_state(), target_component="Final Exam", target_letter="F")


def test_solve_requires_exactly_one_target_kind():
    recon = accepted(phys_207_model(with_replacement=False), PHYS_207_CONTENT)
    with pytest.raises(GradeInputValidationError):
        solve_required_score(recon, phys_207_state(), target_component="Final Exam")
    with pytest.raises(GradeInputValidationError):
        solve_required_score(
            recon, phys_207_state(), target_component="Final Exam", target_grade=90, target_letter="A"
        )


# --- replacement rule (section 42) ---------------------------------------------------


def test_replacement_no_trigger_when_source_below_target():
    recon = accepted(phys_207_model(with_replacement=True), PHYS_207_CONTENT)
    state = phys_207_state()
    state.category_scores.append(CategoryScoreInput(category_name="Final Exam", actual_score=70))  # < 78
    result = calculate_grade_projection(recon, state)
    midterm = next(c for c in result.components if c.name == "Mid-term Exam")
    assert midterm.effective_score == 78
    assert result.applied_rules[0].changed_calculation is False


def test_replacement_triggers_when_source_above_target():
    recon = accepted(phys_207_model(with_replacement=True), PHYS_207_CONTENT)
    state = phys_207_state()
    state.category_scores.append(CategoryScoreInput(category_name="Final Exam", actual_score=88))  # > 78
    result = calculate_grade_projection(recon, state)
    midterm = next(c for c in result.components if c.name == "Mid-term Exam")
    assert midterm.effective_score == 88
    assert midterm.original_score == 78  # original student input untouched
    assert result.applied_rules[0].changed_calculation is True


def test_replacement_does_not_mutate_original_student_input():
    recon = accepted(phys_207_model(with_replacement=True), PHYS_207_CONTENT)
    state = phys_207_state()
    state.category_scores.append(CategoryScoreInput(category_name="Final Exam", actual_score=88))
    before = state.model_dump(mode="json")
    calculate_grade_projection(recon, state)
    after = state.model_dump(mode="json")
    assert before == after


def test_calculation_breakdown_records_effective_replacement():
    recon = accepted(phys_207_model(with_replacement=True), PHYS_207_CONTENT)
    state = phys_207_state()
    state.category_scores.append(CategoryScoreInput(category_name="Final Exam", actual_score=88))
    result = calculate_grade_projection(recon, state)
    rule = result.applied_rules[0]
    assert rule.rule_type == GradingRuleType.REPLACEMENT
    assert rule.source == "Final Exam"
    assert rule.target == "Mid-term Exam"
    assert rule.changed_calculation is True


def test_solver_handles_piecewise_replacement_branch():
    recon = accepted(phys_207_model(with_replacement=True), PHYS_207_CONTENT)
    result = solve_required_score(recon, phys_207_state(), target_component="Final Exam", target_grade=80)
    assert result.required_score == pytest.approx(78.35, abs=0.01)
    assert result.required_score > 78  # replacement-active branch is valid


def test_phys_207_target_b_approx():
    recon = accepted(phys_207_model(with_replacement=True), PHYS_207_CONTENT)
    result = solve_required_score(recon, phys_207_state(), target_component="Final Exam", target_grade=80)
    assert result.required_score == pytest.approx(78.352941, abs=0.01)


def test_phys_207_target_a_approx():
    recon = accepted(phys_207_model(with_replacement=True), PHYS_207_CONTENT)
    result = solve_required_score(recon, phys_207_state(), target_component="Final Exam", target_grade=90)
    assert result.required_score == pytest.approx(90.117647, abs=0.01)


def test_unrecognized_condition_rejected():
    model = phys_207_model(with_replacement=False)
    model.rules.append(
        GradingRule(
            rule_type=GradingRuleType.REPLACEMENT,
            description="Weird condition",
            source="Final Exam",
            target="Mid-term Exam",
            condition="final_score >= midterm_score or attendance > 90",
            evidence=evidence(1, "weird"),
        )
    )
    content = content_for(PHYS_207_MARKDOWN + " weird")
    recon = accepted(model, content)
    state = phys_207_state()
    state.category_scores.append(CategoryScoreInput(category_name="Final Exam", actual_score=88))
    with pytest.raises(UnsupportedRuleConditionError):
        calculate_grade_projection(recon, state)


def test_no_eval_exec_behavior():
    """A condition string that would be dangerous if eval()'d must never
    execute -- it should simply be rejected as unrecognized.
    """
    model = phys_207_model(with_replacement=False)
    model.rules.append(
        GradingRule(
            rule_type=GradingRuleType.REPLACEMENT,
            description="malicious-looking condition",
            source="Final Exam",
            target="Mid-term Exam",
            condition="__import__('os').system('echo pwned')",
            evidence=evidence(1, "malicious"),
        )
    )
    content = content_for(PHYS_207_MARKDOWN + " malicious")
    recon = accepted(model, content)
    state = phys_207_state()
    state.category_scores.append(CategoryScoreInput(category_name="Final Exam", actual_score=88))
    with pytest.raises(UnsupportedRuleConditionError):
        calculate_grade_projection(recon, state)


# --- drop rule (section 43) -----------------------------------------------------------


def test_drop_rule_is_unsupported_and_does_not_execute():
    # Phase 5 always flags an unresolved DROP rule as non_deterministic_grading_rule
    # (review-required), so an ACCEPTED model can never legitimately carry one
    # through reconcile_grade_model -- construct the ACCEPTED result directly to
    # exercise the calculator's own defensive handling of that edge case
    # (see models.py: "still defensively handling malformed direct callers").
    model = phys_207_model(with_replacement=False)
    model.rules.append(
        GradingRule(
            rule_type=GradingRuleType.DROP,
            description="Drop the lowest quiz score.",
            target="Lecture Quizzes",
            evidence=evidence(1, "Drop the lowest quiz score."),
        )
    )
    result_from_reconciliation = reconcile_grade_model(model, PHYS_207_CONTENT)
    recon = GradeModelReconciliationResult.model_construct(
        schema_version=result_from_reconciliation.schema_version,
        status=ReconciliationStatus.ACCEPTED,
        grade_model=model,
        findings=result_from_reconciliation.findings,
        evidence_coverage=result_from_reconciliation.evidence_coverage,
    )
    result = calculate_grade_projection(recon, phys_207_state())
    # Fails explicitly via a clear warning; scores are used unmodified.
    assert any("drop" in w.lower() and "cannot be executed" in w for w in result.warnings)
    assert not any(r.rule_type == GradingRuleType.DROP for r in result.applied_rules)
    assert result.current_grade == 81.4  # unaffected -- no silent dropping


def test_no_assumption_of_equal_weighting_for_drop():
    from GradusIQ_career.syllabus.calculator.rules import is_rule_supported

    rule = GradingRule(rule_type=GradingRuleType.DROP, description="Drop lowest.", target="Lecture Quizzes")
    assert is_rule_supported(rule) is False


def test_drop_rule_never_silently_changes_a_category_score():
    model = phys_207_model(with_replacement=False)
    model.rules.append(GradingRule(rule_type=GradingRuleType.DROP, description="Drop lowest quiz."))
    result_from_reconciliation = reconcile_grade_model(model, PHYS_207_CONTENT)
    recon = GradeModelReconciliationResult.model_construct(
        schema_version=result_from_reconciliation.schema_version,
        status=ReconciliationStatus.ACCEPTED,
        grade_model=model,
        findings=result_from_reconciliation.findings,
        evidence_coverage=result_from_reconciliation.evidence_coverage,
    )
    result = calculate_grade_projection(recon, phys_207_state())
    quizzes = next(c for c in result.components if c.name == "Lecture Quizzes")
    assert quizzes.effective_score == quizzes.original_score == 92


# --- grading method coherence -----------------------------------------------------------


def test_hybrid_with_only_weighted_components_supported():
    # No categories: Phase 5's weight-total check only inspects
    # GradeCategory.weight (a discovered gap -- see the final report's
    # design-decisions section), so a category-less, standalone-weighted-
    # assessment-only model is used here to reach ACCEPTED cleanly.
    model = GradeModel(
        grading_method=GradingMethod.HYBRID,
        assessments=[
            Assessment(name="Exams", weight=70, evidence=evidence(1, "Exams: 70%")),
            Assessment(name="Bonus Quiz", weight=30, evidence=evidence(1, "Bonus Quiz: 30%")),
        ],
    )
    content = content_for("Exams: 70% Bonus Quiz: 30%")
    recon = accepted(model, content)
    state = StudentGradeState(
        assessment_scores=[
            AssessmentScoreInput(assessment_name="Exams", actual_score=90),
            AssessmentScoreInput(assessment_name="Bonus Quiz", actual_score=80),
        ],
    )
    result = calculate_grade_projection(recon, state)
    assert result.projected_grade == round(90 * 0.7 + 80 * 0.3, 2)


def test_hybrid_with_point_assessments_unsupported():
    model = GradeModel(
        grading_method=GradingMethod.HYBRID,
        assessments=[
            Assessment(name="Exams", weight=100, evidence=evidence(1, "Exams: 100%")),
            Assessment(name="Project", points=100, evidence=evidence(1, "Project: 100 points")),
        ],
    )
    content = content_for("Exams: 100% Project: 100 points")
    recon = accepted(model, content)
    with pytest.raises(UnsupportedGradingStructureError):
        calculate_grade_projection(recon, StudentGradeState())


# --- determinism / immutability (section 44) --------------------------------------------


def test_calculation_is_deterministic():
    recon = accepted(phys_207_model(with_replacement=True), PHYS_207_CONTENT)
    state = phys_207_state()
    state.category_scores.append(CategoryScoreInput(category_name="Final Exam", actual_score=88))
    first = calculate_grade_projection(recon, state)
    second = calculate_grade_projection(recon, state)
    assert first == second


def test_solver_is_deterministic():
    recon = accepted(phys_207_model(with_replacement=True), PHYS_207_CONTENT)
    first = solve_required_score(recon, phys_207_state(), target_component="Final Exam", target_grade=80)
    second = solve_required_score(recon, phys_207_state(), target_component="Final Exam", target_grade=80)
    assert first == second


def test_calculator_does_not_mutate_reconciliation_result():
    recon = accepted(phys_207_model(with_replacement=True), PHYS_207_CONTENT)
    before = recon.model_dump(mode="json")
    state = phys_207_state()
    state.category_scores.append(CategoryScoreInput(category_name="Final Exam", actual_score=88))
    calculate_grade_projection(recon, state)
    after = recon.model_dump(mode="json")
    assert before == after


def test_calculator_does_not_mutate_grade_state():
    recon = accepted(phys_207_model(with_replacement=False), PHYS_207_CONTENT)
    state = phys_207_state()
    before = state.model_dump(mode="json")
    calculate_grade_projection(recon, state)
    after = state.model_dump(mode="json")
    assert before == after
