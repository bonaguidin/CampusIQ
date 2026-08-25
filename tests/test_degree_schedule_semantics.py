from datetime import date

from GradusIQ_career.course_discovery.models import CatalogInstitution, CourseCatalogRecord
from GradusIQ_career.degree_schedule_semantics import (
    DEGREE_SCHEDULE_PLANNER_CONTRACT_VERSION,
    build_degree_schedule_semantic_snapshot,
    local_catalog_semantics_fingerprint,
)


def record(
    *,
    institution=CatalogInstitution.SMU,
    code="CS 200",
    prerequisite_text="Prerequisite: MATH 101 with a grade of C or better",
    prerequisite_courses=None,
    **changes,
):
    values = {
        "institution": institution,
        "course_code": code,
        "title": "Display title",
        "description": "Display description",
        "department": "CS",
        "credit_min": 3,
        "credit_max": 3,
        "prerequisite_text": prerequisite_text,
        "prerequisite_courses": prerequisite_courses or ["MATH 101"],
        "restrictions": ["unused imported metadata"],
        "cross_listings": [],
        "catalog_year": "2026-2027",
        "source_url": "https://example.test/one",
        "source_last_checked": "2026-08-01",
    }
    values.update(changes)
    return CourseCatalogRecord(**values)


def fingerprint(*records, institution=CatalogInstitution.SMU):
    return local_catalog_semantics_fingerprint(institution, records)


def test_local_semantic_fingerprint_is_stable_cryptographic_and_order_independent():
    one = record(code="CS 200")
    two = record(code="CS 300", prerequisite_text=None, prerequisite_courses=[])
    reordered_properties = CourseCatalogRecord(**dict(reversed(list(one.model_dump().items()))))
    assert fingerprint(one, two) == fingerprint(two, one)
    assert fingerprint(one) == fingerprint(reordered_properties)
    assert fingerprint(one, two).startswith("sha256:")
    assert len(fingerprint(one, two)) == 71


def test_display_only_local_catalog_changes_do_not_change_fingerprint():
    before = record()
    after = before.model_copy(update={
        "title": "Corrected title",
        "description": "Corrected description",
        "source_url": "https://example.test/two",
        "source_last_checked": "2026-08-24",
        "catalog_year": "2027-2028",
        "restrictions": ["still unused imported metadata"],
    })
    assert fingerprint(before) == fingerprint(after)


def test_prerequisite_grade_and_alternate_path_changes_change_fingerprint():
    baseline = record()
    grade = record(prerequisite_text="Prerequisite: MATH 101 with a grade of B or better")
    alternate = record(prerequisite_text="Prerequisite: MATH 101 or permission of instructor")
    assert fingerprint(baseline) != fingerprint(grade)
    assert fingerprint(baseline) != fingerprint(alternate)


def test_corequisite_and_restriction_semantics_change_fingerprint():
    baseline = record(prerequisite_text=None, prerequisite_courses=[])
    corequisite = record(
        prerequisite_text="Corequisite: MATH 101", prerequisite_courses=["MATH 101"]
    )
    restriction = record(
        prerequisite_text="Junior standing", prerequisite_courses=[]
    )
    assert fingerprint(baseline) != fingerprint(corequisite)
    assert fingerprint(baseline) != fingerprint(restriction)


def test_canonical_course_identity_and_institution_scope_change_fingerprint():
    smu = record(code="CS 200")
    renamed = record(code="CS 201")
    assert fingerprint(smu) != fingerprint(renamed)
    assert fingerprint(smu, institution=CatalogInstitution.SMU) != fingerprint(
        smu, institution=CatalogInstitution.TAMU
    )


def test_semantic_snapshot_is_immutable_and_carries_explicit_contract_and_date():
    snapshot = build_degree_schedule_semantic_snapshot(
        institution=CatalogInstitution.SMU,
        records=[record()],
        reconstruction_date=date(2026, 8, 24),
    )
    assert snapshot.planner_contract_version == DEGREE_SCHEDULE_PLANNER_CONTRACT_VERSION
    assert snapshot.reconstruction_date == date(2026, 8, 24)
