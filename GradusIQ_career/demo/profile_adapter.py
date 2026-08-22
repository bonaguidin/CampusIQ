"""Build a StudentIntelligenceProfile from a flat demo JSON file, not Postgres.

Demo students (data/students/student_<slug>.json) have no rows anywhere in
Supabase -- by design, see api.py's DEMO_STUDENT_SLUGS comment. Course
Discovery and Action Planning are otherwise fully local/DB-free (one LLM
call aside; see course_discovery/agent.py), so the only missing piece to run
them for a demo student is this adapter: the same field assembly
profile_builder.build_student_intelligence_profile does from Postgres rows,
done here from the parsed JSON dict instead.
"""

from __future__ import annotations

from typing import Any, Mapping

from GradusIQ_career.student_intelligence_profile import (
    AcademicCompleteness,
    AcademicCourse,
    Academics,
    AcademicSummary,
    Career,
    CareerCompleteness,
    CareerItem,
    Completeness,
    GpaProfile,
    Identity,
    InstitutionProfile,
    Provenance,
    Skills,
    StudentIntelligenceProfile,
)

DEMO_SOURCE = "demo_seed"
_COMPLETED_WORKFLOW_STATES = {"completed"}
_COMPLETED_ENROLLMENT_STATES = {"completed"}
_EXCLUDED_WORKFLOW_STATES = {"deleted", "inactive"}


def _course_status(course: Mapping[str, Any], enrollment: Mapping[str, Any] | None) -> str:
    if course.get("workflow_state") in _COMPLETED_WORKFLOW_STATES:
        return "completed"
    if enrollment and enrollment.get("enrollment_state") in _COMPLETED_ENROLLMENT_STATES:
        return "completed"
    return "in_progress"


def _letter_grade(enrollment: Mapping[str, Any] | None) -> str | None:
    if not enrollment:
        return None
    grades = enrollment.get("grades") or {}
    return grades.get("final_grade") or grades.get("current_grade")


def _career_items(entries: list[Mapping[str, Any]] | None) -> list[CareerItem]:
    return [CareerItem.model_validate({**item, "source": DEMO_SOURCE}) for item in entries or []]


def build_demo_intelligence_profile(profile_json: Mapping[str, Any]) -> StudentIntelligenceProfile:
    """Pure function: flat demo JSON dict -> validated StudentIntelligenceProfile.

    No I/O, no Supabase client. `career.confirmed` is hardcoded True -- the
    flat JSON has no confirmed_at concept, and Course Discovery's caller-side
    gate (api.py's role-selection check) requires it to be True for any
    target role to ever be selectable.
    """
    student = profile_json["student"]
    courses = profile_json.get("courses") or []
    enrollments_by_course_id = {
        enrollment["course_id"]: enrollment for enrollment in profile_json.get("enrollments") or []
    }
    career = profile_json.get("career") or {}
    skills_self_reported = career.get("skills_self_reported") or {}

    academic_courses: list[AcademicCourse] = []
    for course in courses:
        if course.get("workflow_state") in _EXCLUDED_WORKFLOW_STATES:
            continue
        enrollment = enrollments_by_course_id.get(course["id"])
        academic_courses.append(
            AcademicCourse(
                id=str(course["id"]),
                term_id=None,
                institution_id=None,
                course_code=course["course_code"],
                title=course.get("name"),
                credit_hours=float(course["credit_hours"]),
                letter_grade=_letter_grade(enrollment),
                credit_type="resident",
                status=_course_status(course, enrollment),
                source=DEMO_SOURCE,
            )
        )
    completed_hours = sum(c.credit_hours for c in academic_courses if c.status == "completed")
    in_progress_hours = sum(c.credit_hours for c in academic_courses if c.status == "in_progress")

    academics = Academics(
        summary=AcademicSummary(
            major_current=student.get("major_current"),
            major_intended=student.get("major_intended"),
            confirmed_course_count=len(academic_courses),
            completed_hours=completed_hours,
            in_progress_hours=in_progress_hours,
            earned_hours=completed_hours,
        ),
        terms=[],
        courses=academic_courses,
        gpa=GpaProfile(
            official=student.get("gpa_current"),
            projected=student.get("gpa_current"),
            computable=student.get("gpa_current") is not None,
            in_progress_with_current_grade_count=sum(
                1 for c in academic_courses if c.status == "in_progress" and c.letter_grade
            ),
        ),
        repeat_exclusions=[],
    )

    career_model = Career(
        confirmed=True,
        target_roles=career.get("target_roles") or [],
        interests=career.get("interests") or [],
        career_goals=career.get("career_goals"),
        geographic_preference=career.get("geographic_preference"),
        ai_anxiety_level=career.get("ai_anxiety_level"),
        skills=Skills(
            technical=skills_self_reported.get("technical") or [],
            soft=skills_self_reported.get("soft") or [],
            ai_exposure=skills_self_reported.get("ai_exposure"),
        ),
        certifications=_career_items(career.get("certifications")),
        work_experience=_career_items(career.get("work_experience")),
        projects=_career_items(career.get("projects")),
    )

    career_ready = bool(
        career_model.confirmed
        and career_model.target_roles
        and (career_model.skills.technical or career_model.skills.soft)
    )
    academic_ready = bool(academics.courses and academics.terms)  # terms always [] for demo
    completeness = Completeness(
        career=CareerCompleteness(
            confirmed_profile=career_model.confirmed,
            target_role_present=bool(career_model.target_roles),
            skills_present=bool(career_model.skills.technical or career_model.skills.soft),
            certifications_present=bool(career_model.certifications),
            work_experience_present=bool(career_model.work_experience),
            projects_present=bool(career_model.projects),
            ready_for_career_features=career_ready,
        ),
        academics=AcademicCompleteness(
            transcript_data_present=bool(academics.courses),
            terms_present=bool(academics.terms),
            gpa_computable=academics.gpa.computable,
            ready_for_academic_features=academic_ready,
        ),
        overall="ready" if career_ready and academic_ready else "partial" if career_ready or academic_ready else "minimal",
    )

    return StudentIntelligenceProfile(
        identity=Identity(
            student_id=str(student["id"]),
            name=student.get("name"),
            classification=student.get("classification"),
            expected_graduation=student.get("expected_graduation"),
            onboarding_stage=profile_json.get("onboarding_stage"),
        ),
        institution=InstitutionProfile(
            id=None,
            name=student.get("institution"),
            relationship="home",
        ),
        academics=academics,
        career=career_model,
        completeness=completeness,
        provenance=Provenance(
            career_profile=DEMO_SOURCE,
            certifications=[DEMO_SOURCE] if career_model.certifications else [],
            work_experience=[DEMO_SOURCE] if career_model.work_experience else [],
            projects=[DEMO_SOURCE] if career_model.projects else [],
            academics=[DEMO_SOURCE] if academic_courses else [],
            credit_type_limitation=None,
        ),
    )
