"""Storage contract for persisted structured-requirement exclusions.

Parallel to requirement_selections.py. A row here is the student's intent to
remove an otherwise no-choice requirement group from their Degree Schedule; it
is not proof the requirement stopped applying. Reconstruction revalidates the
current requirement tree before an exclusion is allowed to affect scheduling.
"""

from typing import Any


def load_requirement_exclusion_group_ids(
    client: Any, student_id: str, program_id: str
) -> tuple[str, ...]:
    """The requirement group ids this student has set aside for this program.

    Runs under the caller's own session client -- the owner SELECT RLS policy
    (degree_requirement_exclusions_owner_select) is the real access control;
    the explicit student_id filter is belt-and-braces alongside it, the same
    posture load_requirement_selection_identities takes.
    """
    rows = (
        client.table("degree_requirement_exclusions")
        .select("requirement_group_id")
        .eq("student_id", student_id)
        .eq("program_id", program_id)
        .execute()
        .data
        or []
    )
    return tuple(sorted(str(row["requirement_group_id"]) for row in rows))
