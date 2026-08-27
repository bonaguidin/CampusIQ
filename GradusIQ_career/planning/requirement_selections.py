"""Storage contract for persisted structured-requirement choices.

The stored candidate ID and course path are student intent/provenance. They do
not establish current academic validity; reconstruction must revalidate them
against current candidate evidence before they may affect scheduling.
"""

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class RequirementSelectionIdentity:
    program_id: str
    requirement_group_id: str
    candidate_id: str
    course_codes: tuple[str, ...]

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "RequirementSelectionIdentity":
        return cls(
            program_id=str(row["program_id"]),
            requirement_group_id=str(row["requirement_group_id"]),
            candidate_id=str(row["candidate_id"]),
            course_codes=tuple(str(code) for code in row["course_codes"]),
        )


@dataclass(frozen=True)
class PersistedRequirementSelection:
    id: str
    student_id: str
    program_id: str
    requirement_group_id: str
    candidate_id: str
    course_codes: tuple[str, ...]
    decision_version: str
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "PersistedRequirementSelection":
        return cls(
            id=str(row["id"]),
            student_id=str(row["student_id"]),
            program_id=str(row["program_id"]),
            requirement_group_id=str(row["requirement_group_id"]),
            candidate_id=str(row["candidate_id"]),
            course_codes=tuple(str(code) for code in row["course_codes"]),
            decision_version=str(row["decision_version"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )


def load_requirement_selection_identities(
    client: Any, student_id: str, program_id: str
) -> tuple[RequirementSelectionIdentity, ...]:
    rows = (
        client.table("degree_requirement_selections")
        .select("program_id,requirement_group_id,candidate_id,course_codes")
        .eq("student_id", student_id)
        .eq("program_id", program_id)
        .execute()
        .data
        or []
    )
    return tuple(sorted(
        (RequirementSelectionIdentity.from_row(row) for row in rows),
        key=lambda item: (item.requirement_group_id, item.candidate_id),
    ))
