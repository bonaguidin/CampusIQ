from copy import deepcopy
from dataclasses import replace
from datetime import date
from types import SimpleNamespace

from GradusIQ_career.course_discovery.models import StructuredPrerequisite
from GradusIQ_career.course_discovery.requirement_candidates import (
    AcademicFeasibility,
    RequirementCandidate,
    RequirementCandidateSet,
    RequirementDecision,
    RequirementDecisionState,
)
from GradusIQ_career.degree_schedule_version import (
    DEGREE_SCHEDULE_CONTRACT_VERSION,
    build_degree_schedule_version,
)
from GradusIQ_career.degree_schedule_semantics import DegreeScheduleSemanticSnapshot


def _state():
    candidate = RequirementCandidate(
        candidate_id="reqcand_one", requirement_group_id="group-1",
        requirement_name="Display name", course_codes=["CS 101"],
        existing_contribution=0, additional_course_count=1, additional_credits=3,
        academic_feasibility=AcademicFeasibility.FEASIBLE,
        completion_term_index=0, source_order=[0],
    )
    return SimpleNamespace(
        student_id="student-1", program_id="program-1",
        starting_year=2026, starting_season="Fall", max_terms=6,
        raw=SimpleNamespace(
            groups=[{
                "id": "group-1", "program_id": "program-1", "catalog_year": "2026-2027",
                "coursedog_rule_id": "rule-1", "parent_group_id": None,
                "name": "Display name", "group_type": "enumerated_all",
                "n_required": None, "credit_hours_required": None,
                "notes_html": None, "requires_manual_definition": False,
            }],
            options=[{
                "id": "option-db-id", "requirement_group_id": "group-1",
                "option_index": 0, "logic": "and",
            }],
            option_courses=[{
                "requirement_group_option_id": "option-db-id",
                "coursedog_group_id": "catalog-group-1", "course_code": None,
                "unresolved_course_ref": None,
            }],
            course_records=[],
            catalog_credit_by_code={"CS 101": 3.0},
        ),
        prerequisites={"CS 101": StructuredPrerequisite()},
        academic_selection=SimpleNamespace(
            candidate_sets=[RequirementCandidateSet(
                requirement_group_id="group-1", requirement_name="Display name",
                feasible_candidates=[candidate],
            )],
            decisions=[RequirementDecision(
                requirement_group_id="group-1", requirement_name="Display name",
                state=RequirementDecisionState.AUTO_SELECTED,
                feasible_candidate_ids=["reqcand_one"], selected_candidate_id="reqcand_one",
            )],
        ),
        # Deliberately unused: title-only display changes cannot invalidate.
        catalog_by_code={"CS 101": SimpleNamespace(title="Original title", credit_min=3)},
        semantic_snapshot=DegreeScheduleSemanticSnapshot(
            planner_contract_version="1",
            local_catalog_fingerprint="sha256:" + "a" * 64,
            reconstruction_date=date(2026, 8, 19),
        ),
        active_selections=[],
    )


def test_schedule_version_is_stable_and_cryptographic():
    state = _state()
    first = build_degree_schedule_version(state)
    second = build_degree_schedule_version(deepcopy(state))
    assert first == second
    assert first.startswith("sha256:") and len(first) == len("sha256:") + 64
    assert DEGREE_SCHEDULE_CONTRACT_VERSION == "2"


def test_schedule_version_changes_for_candidate_decision_semantics():
    before = _state()
    after = deepcopy(before)
    after.academic_selection.candidate_sets[0].feasible_candidates[0].completion_term_index = 1
    assert build_degree_schedule_version(before) != build_degree_schedule_version(after)


def test_schedule_version_changes_for_course_record_state():
    before = _state()
    after = deepcopy(before)
    after.raw.course_records.append({
        "course_code": "MATH 101", "status": "completed", "credit_hours": 3,
        "counts_toward_credit": True, "term_id": "term-1",
    })
    assert build_degree_schedule_version(before) != build_degree_schedule_version(after)


def test_schedule_version_excludes_display_title_but_includes_academic_credit():
    before = _state()
    title_only = deepcopy(before)
    title_only.catalog_by_code["CS 101"].title = "Corrected display title"
    assert build_degree_schedule_version(before) == build_degree_schedule_version(title_only)

    credit_change = deepcopy(before)
    credit_change.raw.catalog_credit_by_code["CS 101"] = 4
    assert build_degree_schedule_version(before) != build_degree_schedule_version(credit_change)


def test_schedule_version_excludes_database_option_row_identity():
    before = _state()
    rebuilt = deepcopy(before)
    rebuilt.raw.options[0]["id"] = "replacement-option-db-id"
    rebuilt.raw.option_courses[0]["requirement_group_option_id"] = "replacement-option-db-id"
    assert build_degree_schedule_version(before) == build_degree_schedule_version(rebuilt)


def test_schedule_version_includes_semantic_fingerprint_contract_and_date():
    before = _state()
    fingerprint = deepcopy(before)
    fingerprint.semantic_snapshot = replace(
        fingerprint.semantic_snapshot,
        local_catalog_fingerprint="sha256:" + "b" * 64,
    )
    contract = deepcopy(before)
    contract.semantic_snapshot = replace(
        contract.semantic_snapshot, planner_contract_version="2"
    )
    reconstruction_date = deepcopy(before)
    reconstruction_date.semantic_snapshot = replace(
        reconstruction_date.semantic_snapshot,
        reconstruction_date=date(2026, 8, 20),
    )
    assert build_degree_schedule_version(before) != build_degree_schedule_version(fingerprint)
    assert build_degree_schedule_version(before) != build_degree_schedule_version(contract)
    assert build_degree_schedule_version(before) != build_degree_schedule_version(reconstruction_date)


def test_schedule_version_includes_only_canonical_active_selection_identity():
    none = _state()
    selected = deepcopy(none)
    selected.active_selections = [{
        "id": "storage-one",
        "program_id": "program-1",
        "requirement_group_id": "group-1",
        "candidate_id": "reqcand_one",
        "course_codes": ["CS 101", "CS 102"],
        "created_at": "yesterday",
    }]
    recreated = deepcopy(selected)
    recreated.active_selections[0]["id"] = "storage-two"
    recreated.active_selections[0]["created_at"] = "today"
    replaced = deepcopy(selected)
    replaced.active_selections[0]["candidate_id"] = "reqcand_two"
    path_changed = deepcopy(selected)
    path_changed.active_selections[0]["course_codes"] = ["CS 101", "CS 103"]
    reordered = deepcopy(selected)
    reordered.active_selections.append({
        "program_id": "program-1", "requirement_group_id": "group-2",
        "candidate_id": "reqcand_three", "course_codes": ["MATH 101"],
    })
    reverse_order = deepcopy(reordered)
    reverse_order.active_selections.reverse()

    assert build_degree_schedule_version(none) != build_degree_schedule_version(selected)
    assert build_degree_schedule_version(selected) == build_degree_schedule_version(recreated)
    assert build_degree_schedule_version(selected) != build_degree_schedule_version(replaced)
    assert build_degree_schedule_version(selected) != build_degree_schedule_version(path_changed)
    assert build_degree_schedule_version(reordered) == build_degree_schedule_version(reverse_order)
