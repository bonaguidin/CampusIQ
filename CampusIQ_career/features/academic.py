"""Professor comment analyzer feature runner."""

from typing import Any, Mapping

from .base import CareerFeatureRunner


class AcademicRunner(CareerFeatureRunner):
    feature = "PROFESSOR_COMMENTS"
    prompt_filename = "campus_iq_prompt_ACADEMIC.md"
    role = "academic"
    # NOTE: get_path() only supports dot-separated dict keys, not list
    # indexing, so "submissions[].submission_comments[]" cannot be used
    # here directly. "submissions" (checked for non-emptiness) is the
    # closest real top-level field find_missing_fields can evaluate.
    required_paths = ("submissions",)
    output_contract: Mapping[str, Any] = {
        "themes": [
            {
                "theme": "string",
                "category": "strength|concern|praise|flag",
                "summary": "string",
                "supporting_references": [
                    {
                        "course_code": "string",
                        "course_name": "string",
                        "paraphrase": "string",
                    }
                ],
            }
        ],
        "overall_summary": "string",
    }

    def build_student_context(self, student_profile):
        assignments = {
            assignment.get("id"): assignment
            for assignment in student_profile.get("assignments", [])
        }
        courses = {
            course.get("id"): course
            for course in student_profile.get("courses", [])
        }

        comments_by_course: dict[Any, dict[str, Any]] = {}
        for submission in student_profile.get("submissions", []):
            comments = submission.get("submission_comments", [])
            if not comments:
                continue

            assignment = assignments.get(submission.get("assignment_id"), {})
            course = courses.get(assignment.get("course_id"), {})
            course_key = course.get("id")

            bucket = comments_by_course.setdefault(
                course_key,
                {
                    "course_code": course.get("course_code"),
                    "course_name": course.get("name"),
                    "comments": [],
                },
            )
            for comment in comments:
                bucket["comments"].append(
                    {
                        "assignment_name": assignment.get("name"),
                        "author_name": comment.get("author_name"),
                        "comment": comment.get("comment"),
                        "created_at": comment.get("created_at"),
                    }
                )

        return {
            "comments_by_course": list(comments_by_course.values()),
        }

    def default_summary(self, data):
        return data.get("overall_summary", "Professor comment analysis completed.")
