"""Focused contract tests for the authenticated canonical profile adapter."""

from copy import deepcopy

import pytest

from GradusIQ_career.profile_builder import build_student_intelligence_profile
from GradusIQ_career.student_intelligence_profile import StudentIntelligenceProfile


CONFIRMED = "2026-08-01T00:00:00Z"
SID = "student-a"
IID = "institution-a"


class FakeSupabase:
    def __init__(self, tables):
        self.tables = tables
        self.rows = []
        self.queried = []

    def table(self, name):
        self.queried.append(name)
        self.rows = list(self.tables.get(name, []))
        return self

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, key, value):
        self.rows = [row for row in self.rows if row.get(key) == value]
        return self

    def execute(self):
        return type("Response", (), {"data": self.rows})()


def tables(*, institution="Texas A&M University"):
    return {
        "students": [{
            "id": SID, "name": "Student A", "classification": "Sophomore",
            "major_current": "Engineering", "major_intended": None,
            "expected_graduation": "2028-05", "onboarding_stage": 3,
        }],
        "student_institutions": [{
            "student_id": SID, "institution_id": IID, "relationship": "home",
        }],
        "institutions": [{
            "id": IID, "name": institution, "uses_plus_minus": True,
            "transfer_grades_count_toward_gpa": False,
        }],
        "grade_point_map": [{
            "institution_id": IID, "letter": "A", "points": 4.0,
            "counts_toward_gpa": True, "counts_toward_credit": True,
        }],
        "career_profiles": [{
            "id": "career-a", "student_id": SID, "target_roles": ["Engineer"],
            "interests": ["systems"], "career_goals": "Build things",
            "skills_technical": ["Python"], "skills_soft": ["writing"],
            "ai_exposure": "coursework", "source": "resume_parse",
            "confirmed_at": CONFIRMED,
        }],
        "certifications": [{
            "id": "cert-a", "career_profile_id": "career-a", "student_id": SID,
            "name": "Cloud", "source": "resume_parse", "confirmed_at": CONFIRMED,
        }],
        "work_experience": [{
            "id": "work-a", "career_profile_id": "career-a", "student_id": SID,
            "employer": "Acme", "source": "resume_parse", "confirmed_at": CONFIRMED,
        }],
        "projects": [{
            "id": "project-a", "career_profile_id": "career-a", "student_id": SID,
            "name": "Robot", "source": "manual", "confirmed_at": CONFIRMED,
        }],
        "academic_terms": [{
            "id": "term-a", "student_id": SID, "institution_id": IID,
            "label": "Fall 2025", "year": 2025, "season": "fall", "sequence": 1,
        }],
        "course_records": [{
            "id": "course-a", "student_id": SID, "term_id": "term-a",
            "institution_id": IID, "course_code": "ENGR 101", "title": "Intro",
            "credit_hours": 3, "letter_grade": "A", "credit_type": "resident",
            "status": "completed", "source": "transcript_parse",
            "confirmed_at": CONFIRMED, "excluded_from_gpa_by": None,
        }],
    }


def build(value):
    return build_student_intelligence_profile(FakeSupabase(value), SID)


def test_complete_student_is_validated_and_uses_gpa_service(monkeypatch):
    called = []
    from GradusIQ_career import profile_builder
    real = profile_builder.compute_both

    def spy(records, institution, grade_map):
        called.append((records, institution, grade_map))
        return real(records, institution, grade_map)

    monkeypatch.setattr(profile_builder, "compute_both", spy)
    result = build(tables())

    assert isinstance(result, StudentIntelligenceProfile)
    assert result.academics.gpa.official == 4.0
    assert result.academics.gpa.source == "gpa_service"
    assert result.academics.terms[0].label == "Fall 2025"
    assert result.career.certifications[0].name == "Cloud"
    assert called


@pytest.mark.parametrize("missing", ["academic", "career", "both"])
def test_partial_and_minimal_students_build(missing):
    value = tables()
    if missing in {"academic", "both"}:
        value["academic_terms"] = []
        value["course_records"] = []
    if missing in {"career", "both"}:
        value["career_profiles"] = []
        value["certifications"] = []
        value["work_experience"] = []
        value["projects"] = []

    result = build(value)
    assert isinstance(result, StudentIntelligenceProfile)
    assert result.completeness.overall in {"partial", "minimal"}


def test_pending_career_and_transcript_are_not_promoted():
    value = tables()
    value["career_profiles"][0]["confirmed_at"] = None
    value["course_records"][0]["confirmed_at"] = None

    result = build(value)
    assert result.career.confirmed is False
    assert result.career.target_roles == []
    assert result.academics.courses == []
    assert result.academics.gpa.official is None
    assert result.academics.summary.completed_hours == 0.0


def test_repeat_exclusion_comes_from_course_state():
    value = tables()
    repeated = deepcopy(value["course_records"][0])
    repeated["id"] = "course-b"
    repeated["excluded_from_gpa_by"] = "course-a"
    value["course_records"].append(repeated)

    result = build(value)
    assert result.academics.repeat_exclusions[0].excluded_course_id == "course-b"
    assert result.academics.repeat_exclusions[0].superseded_by_course_id == "course-a"


def test_student_isolation_is_explicit_on_every_student_table_query():
    value = tables()
    other = deepcopy(value["course_records"][0])
    other.update({"id": "course-other", "student_id": "student-b"})
    value["course_records"].append(other)
    result = build(value)
    assert [course.id for course in result.academics.courses] == ["course-a"]


@pytest.mark.parametrize("name", ["Texas A&M University", "Southern Methodist University"])
def test_institution_neutral(name):
    result = build(tables(institution=name))
    assert result.institution.name == name


def test_credit_classification_limitation_is_explicit():
    result = build(tables())
    assert "defaults credit_type to resident" in result.provenance.credit_type_limitation
