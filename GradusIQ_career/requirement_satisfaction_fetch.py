"""Flat, un-recursive fetch of one program's requirement_groups tree plus
one student's course_records -- the data-access boundary for
course_discovery.requirement_satisfaction.evaluate_requirement_tree().

Placed alongside profile_builder.py and supabase_client.py rather than
under course_discovery/ for the same reason profile_builder.py gives for
its own placement: this is a data-access concern, not a feature concern,
and course_discovery/README.md states C1 "does not call ... Supabase" --
this module is the boundary that keeps that true, handing the evaluator
already-fetched plain data the same way build_student_intelligence_
profile() hands CourseDiscoveryService an already-built profile.

No business logic here -- see planning-docs/degree-planner-spec.md §9.1's
"Split for testability": this function is deliberately untested-by-unit-
test, the same treatment profile_builder.py's raw fetches get, since it
is straight-line client.table(...).select(...).eq(...) calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RawTreeInputs:
    groups: list[dict[str, Any]]
    options: list[dict[str, Any]]
    option_courses: list[dict[str, Any]]
    course_records: list[dict[str, Any]]
    catalog_by_gid: dict[str, str] = field(default_factory=dict)


def fetch_requirement_tree(client: Any, program_id: str, student_id: str) -> RawTreeInputs:
    groups = client.table("requirement_groups").select("*").eq("program_id", program_id).execute().data

    group_ids = [group["id"] for group in groups]
    options = (
        client.table("requirement_group_options").select("*").in_("requirement_group_id", group_ids).execute().data
        if group_ids
        else []
    )

    option_ids = [option["id"] for option in options]
    option_courses = (
        client.table("requirement_group_option_courses")
        .select("*")
        .in_("requirement_group_option_id", option_ids)
        .execute()
        .data
        if option_ids
        else []
    )

    course_records = client.table("course_records").select("*").eq("student_id", student_id).execute().data

    catalog_by_gid: dict[str, str] = {}
    coursedog_group_ids = [row["coursedog_group_id"] for row in option_courses if row.get("coursedog_group_id")]
    if coursedog_group_ids:
        program_rows = client.table("programs").select("institution_id").eq("id", program_id).execute().data
        institution_id = program_rows[0]["institution_id"] if program_rows else None
        if institution_id:
            catalog_rows = (
                client.table("course_catalog")
                .select("code,coursedog_group_id")
                .eq("institution_id", institution_id)
                .in_("coursedog_group_id", coursedog_group_ids)
                .execute()
                .data
            )
            catalog_by_gid = {row["coursedog_group_id"]: row["code"] for row in catalog_rows}

    return RawTreeInputs(
        groups=groups,
        options=options,
        option_courses=option_courses,
        course_records=course_records,
        catalog_by_gid=catalog_by_gid,
    )
