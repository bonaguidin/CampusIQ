"""Canonical stale-state versioning for deterministic Degree Schedules.

Display metadata is intentionally absent. The hash covers reconstructed
academic semantics; future active selections can be added as current
requirement/candidate/course-code tuples without hashing their historical
``decision_version`` and creating a circular dependency.
"""

from __future__ import annotations

from decimal import Decimal
import hashlib
import json
from typing import Any, Iterable, Mapping

from GradusIQ_career.degree_schedule_semantics import (
    DEGREE_SCHEDULE_PLANNER_CONTRACT_VERSION,
)


DEGREE_SCHEDULE_CONTRACT_VERSION = DEGREE_SCHEDULE_PLANNER_CONTRACT_VERSION


def _number(value: Any) -> str | None:
    if value is None:
        return None
    decimal = Decimal(str(value))
    rendered = format(decimal.normalize(), "f")
    return "0" if rendered in {"-0", ""} else rendered


def _group_semantics(groups: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    fields = (
        "id", "program_id", "catalog_year", "coursedog_rule_id", "parent_group_id",
        "group_type", "n_required", "credit_hours_required", "notes_html",
        "requires_manual_definition",
    )
    return sorted(
        ({field: group.get(field) for field in fields} for group in groups),
        key=lambda item: str(item["id"]),
    )


def _option_semantics(
    options: Iterable[Mapping[str, Any]],
    option_courses: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    courses_by_option: dict[str, list[dict[str, Any]]] = {}
    for row in option_courses:
        courses_by_option.setdefault(str(row.get("requirement_group_option_id")), []).append({
            "coursedog_group_id": row.get("coursedog_group_id"),
            "course_code": row.get("course_code"),
            "unresolved_course_ref": row.get("unresolved_course_ref"),
        })
    result = []
    for option in options:
        references = sorted(
            courses_by_option.get(str(option.get("id")), []),
            key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
        )
        result.append({
            "requirement_group_id": option.get("requirement_group_id"),
            "option_index": option.get("option_index"),
            "logic": option.get("logic"),
            "course_references": references,
        })
    return sorted(
        result,
        key=lambda item: (
            str(item["requirement_group_id"]), int(item["option_index"] or 0),
            json.dumps(item["course_references"], sort_keys=True, separators=(",", ":")),
        ),
    )


def _candidate_semantics(candidate: Any) -> dict[str, Any]:
    return {
        "candidate_id": candidate.candidate_id,
        "requirement_group_id": candidate.requirement_group_id,
        "course_codes": list(candidate.course_codes),
        "unresolved_course_codes": list(candidate.unresolved_course_codes),
        "existing_contribution": candidate.existing_contribution,
        "additional_course_count": candidate.additional_course_count,
        "additional_credits": _number(candidate.additional_credits),
        "academic_feasibility": candidate.academic_feasibility.value,
        "completion_term_index": candidate.completion_term_index,
        "limitations": sorted(candidate.limitations),
        "source_order": list(candidate.source_order),
        "exclusion_reasons": sorted(reason.value for reason in candidate.exclusion_reasons),
    }


def _selection_value(selection: Any, field: str) -> Any:
    return selection.get(field) if isinstance(selection, Mapping) else getattr(selection, field)


def canonical_active_selection_semantics(selections: Iterable[Any]) -> list[dict[str, Any]]:
    return sorted(
        (
            {
                "program_id": str(_selection_value(item, "program_id")),
                "requirement_group_id": str(_selection_value(item, "requirement_group_id")),
                "candidate_id": str(_selection_value(item, "candidate_id")),
                "course_codes": [str(code) for code in _selection_value(item, "course_codes")],
            }
            for item in selections
        ),
        key=lambda item: (item["requirement_group_id"], item["candidate_id"]),
    )


def build_degree_schedule_version(state: Any) -> str:
    raw = state.raw
    active_selections = tuple(state.active_selections)
    selection_state_status = getattr(
        state, "selection_state_status", "APPLIED" if active_selections else "NONE"
    )
    selection_state_failure = getattr(state, "selection_state_failure", None)
    candidate_sets = []
    for candidate_set in state.academic_selection.candidate_sets:
        candidate_sets.append({
            "requirement_group_id": candidate_set.requirement_group_id,
            "feasible_candidates": sorted(
                (_candidate_semantics(item) for item in candidate_set.feasible_candidates),
                key=lambda item: item["candidate_id"],
            ),
            "excluded_candidates": sorted(
                (_candidate_semantics(item) for item in candidate_set.excluded_candidates),
                key=lambda item: item["candidate_id"],
            ),
        })

    prerequisites = []
    for course_code, prerequisite in state.prerequisites.items():
        prerequisites.append({
            "course_code": course_code,
            "requires_all": [
                {
                    "course_codes": sorted(clause.course_codes),
                    "grade_min": clause.grade_min,
                    "alternate_paths": sorted(clause.alternate_paths),
                }
                for clause in prerequisite.requires_all
            ],
            "coreq_allowed": sorted(prerequisite.coreq_allowed),
            "restrictions": sorted(prerequisite.restrictions),
            "needs_review": sorted(prerequisite.needs_review),
        })

    payload = {
        "contract_version": state.semantic_snapshot.planner_contract_version,
        "semantic_snapshot": {
            "local_catalog_fingerprint": state.semantic_snapshot.local_catalog_fingerprint,
            "reconstruction_date": state.semantic_snapshot.reconstruction_date.isoformat(),
        },
        "student_id": state.student_id,
        "program_id": state.program_id,
        "planning_horizon": {
            "starting_year": state.starting_year,
            "starting_season": state.starting_season,
            "max_terms": state.max_terms,
        },
        "course_records": sorted(
            (
                {
                    "course_code": row.get("course_code"),
                    "status": row.get("status"),
                    "credit_hours": _number(row.get("credit_hours")),
                    "counts_toward_credit": row.get("counts_toward_credit"),
                    "term_id": row.get("term_id"),
                }
                for row in raw.course_records
            ),
            key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
        ),
        "requirements": _group_semantics(raw.groups),
        "options": _option_semantics(raw.options, raw.option_courses),
        "catalog_credits": [
            [code, _number(value)]
            for code, value in sorted(raw.catalog_credit_by_code.items())
        ],
        "prerequisites": sorted(prerequisites, key=lambda item: item["course_code"]),
        "candidate_sets": sorted(candidate_sets, key=lambda item: item["requirement_group_id"]),
        "decisions": sorted(
            (
                {
                    "requirement_group_id": decision.requirement_group_id,
                    "state": decision.state.value,
                    "feasible_candidate_ids": sorted(decision.feasible_candidate_ids),
                    "excluded_candidate_ids": sorted(decision.excluded_candidate_ids),
                    "selected_candidate_id": decision.selected_candidate_id,
                }
                for decision in state.academic_selection.decisions
            ),
            key=lambda item: item["requirement_group_id"],
        ),
        # Persisted identity remains present even when current evidence makes
        # it stale and reconstruction safely falls back to the unlocked plan.
        "active_selections": canonical_active_selection_semantics(
            active_selections
        ),
        "selection_state": {
            "status": selection_state_status,
            "failure_code": (
                selection_state_failure.code.value
                if selection_state_failure is not None
                else None
            ),
        },
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
