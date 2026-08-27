from GradusIQ_career.planning.requirement_selections import PersistedRequirementSelection


def test_persisted_requirement_selection_preserves_atomic_course_order():
    row = {
        "id": "selection-1", "student_id": "student-1", "program_id": "program-1",
        "requirement_group_id": "requirement-1", "candidate_id": "reqcand_abc",
        "course_codes": ["CEE 2302", "CS 3377"],
        "decision_version": "sha256:" + "a" * 64,
        "created_at": "2026-08-24T12:00:00Z", "updated_at": "2026-08-24T12:00:00Z",
    }
    selection = PersistedRequirementSelection.from_row(row)
    assert selection.course_codes == ("CEE 2302", "CS 3377")
    assert selection.candidate_id == "reqcand_abc"

