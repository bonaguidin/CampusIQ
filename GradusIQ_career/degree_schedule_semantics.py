"""Stable semantic identity for one Degree Schedule reconstruction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
from typing import Iterable

from GradusIQ_career.course_discovery.models import CatalogInstitution, CourseCatalogRecord
from GradusIQ_career.course_discovery.prerequisites import structured_prerequisite


# Deliberately bump this for academic policy/code changes: candidate enumeration,
# prerequisite parsing, ownership/double-counting, scheduler policy, credit/horizon
# rules, or locked-selection semantics. Presentation-only changes do not bump it.
DEGREE_SCHEDULE_PLANNER_CONTRACT_VERSION = "2"


@dataclass(frozen=True)
class DegreeScheduleSemanticSnapshot:
    planner_contract_version: str
    local_catalog_fingerprint: str
    reconstruction_date: date


def _prerequisite_semantics(course: CourseCatalogRecord) -> dict[str, object]:
    parsed = structured_prerequisite(course)
    return {
        "course_code": course.course_code,
        "requires_all": sorted(
            (
                {
                    "course_codes": sorted(clause.course_codes),
                    "grade_min": clause.grade_min,
                    "alternate_paths": sorted(clause.alternate_paths),
                }
                for clause in parsed.requires_all
            ),
            key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
        ),
        "coreq_allowed": sorted(parsed.coreq_allowed),
        "restrictions": sorted(parsed.restrictions),
        "needs_review": sorted(parsed.needs_review),
    }


def local_catalog_semantics_fingerprint(
    institution: CatalogInstitution,
    records: Iterable[CourseCatalogRecord],
) -> str:
    """Hash canonical parsed academic semantics for one institution.

    The institution discriminator makes even an empty snapshot scoped. Parsed
    output is shared with scheduling through ``structured_prerequisite`` so a
    second fingerprint-only interpretation cannot drift from academic behavior.
    """
    payload = {
        "institution": institution.value,
        "courses": sorted(
            (_prerequisite_semantics(course) for course in records),
            key=lambda item: str(item["course_code"]),
        ),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_degree_schedule_semantic_snapshot(
    *,
    institution: CatalogInstitution,
    records: Iterable[CourseCatalogRecord] | None = None,
    local_catalog_fingerprint: str | None = None,
    reconstruction_date: date,
    planner_contract_version: str = DEGREE_SCHEDULE_PLANNER_CONTRACT_VERSION,
) -> DegreeScheduleSemanticSnapshot:
    if (records is None) == (local_catalog_fingerprint is None):
        raise ValueError("provide exactly one local catalog semantic source")
    return DegreeScheduleSemanticSnapshot(
        planner_contract_version=planner_contract_version,
        local_catalog_fingerprint=(
            local_catalog_fingerprint
            if local_catalog_fingerprint is not None
            else local_catalog_semantics_fingerprint(institution, records or ())
        ),
        reconstruction_date=reconstruction_date,
    )
