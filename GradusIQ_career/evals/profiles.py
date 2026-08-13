"""Convert small synthetic eval inputs through the canonical profile contract."""

from GradusIQ_career.student_intelligence_profile import StudentIntelligenceProfile

from .models import SyntheticStudentInput


def build_synthetic_canonical_profile(value: SyntheticStudentInput) -> StudentIntelligenceProfile:
    career_present = bool(
        value.target_roles
        or value.interests
        or value.technical_skills
        or value.soft_skills
        or value.experience
        or value.projects
        or value.certifications
        or value.career_goals
    )
    courses = [
        {
            "id": f"eval-course-{index}",
            "course_code": course.course_code,
            "title": course.title,
            "credit_hours": course.credit_hours,
            "letter_grade": course.letter_grade,
            "credit_type": "resident",
            "status": course.status,
            "source": "synthetic_eval",
        }
        for index, course in enumerate(value.completed_courses, 1)
    ]
    skills_present = bool(value.technical_skills or value.soft_skills)
    career_ready = bool(career_present and value.target_roles and skills_present)
    return StudentIntelligenceProfile.model_validate(
        {
            "identity": {
                "student_id": "synthetic-eval-student",
                "name": "Synthetic Student",
                "classification": value.classification,
                "expected_graduation": value.expected_graduation,
            },
            "institution": {"name": "Synthetic University"},
            "academics": {
                "summary": {
                    "major_current": value.current_major,
                    "major_intended": value.intended_major,
                    "confirmed_course_count": len(courses),
                },
                "courses": courses,
                "gpa": {"official": None, "projected": None, "computable": False},
            },
            "career": {
                "confirmed": career_present,
                "target_roles": value.target_roles,
                "interests": value.interests,
                "career_goals": value.career_goals,
                "skills": {
                    "technical": value.technical_skills,
                    "soft": value.soft_skills,
                },
                "certifications": [{"name": name, "source": "synthetic_eval"} for name in value.certifications],
                "work_experience": [item.model_dump() for item in value.experience],
                "projects": [item.model_dump() for item in value.projects],
            },
            "completeness": {
                "career": {
                    "confirmed_profile": career_present,
                    "target_role_present": bool(value.target_roles),
                    "skills_present": skills_present,
                    "certifications_present": bool(value.certifications),
                    "work_experience_present": bool(value.experience),
                    "projects_present": bool(value.projects),
                    "ready_for_career_features": career_ready,
                },
                "academics": {
                    "transcript_data_present": bool(courses),
                    "terms_present": False,
                    "gpa_computable": False,
                    "ready_for_academic_features": False,
                },
                "overall": "partial" if career_present or courses else "minimal",
            },
            "provenance": {},
        }
    )
