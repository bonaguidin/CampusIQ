"""Professor comment analyzer feature runner."""

from typing import Any, Mapping

from .base import CareerFeatureRunner


class AcademicRunner(CareerFeatureRunner):
    feature = "PROFESSOR_COMMENTS"
    prompt_filename = "gradus_iq_prompt_ACADEMIC.md"
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
    # Mirrors the "category": "strength|concern|praise|flag" alternation in
    # output_contract above and the Category list in the prompt's theme
    # heading. Kept as a frozenset so validation reads as a membership test.
    valid_categories = frozenset({"strength", "concern", "praise", "flag"})

    def additional_missing_fields(self, student_profile):
        """Skip when no submission actually carries a comment.

        required_paths can only assert that `submissions` is non-empty. A
        student who has submissions but no feedback on any of them would
        otherwise reach the model with comments_by_course: [] -- an empty but
        well-formed payload, against which the prompt's "do not invent
        feedback" line is the only safeguard. There is nothing to analyze, so
        skip instead of spending a call.
        """
        for submission in student_profile.get("submissions", []):
            if submission.get("submission_comments"):
                return []
        return ["submissions[].submission_comments"]

    def validate_data(self, data, student_profile):
        """Check the response against output_contract, citations included.

        Citation checking is folded in here rather than kept separate: a
        supporting_reference naming a course the student has no comments from
        is not a valid supporting_reference, so it is a contract violation
        like any other. One traversal, one failure mode, one error list.
        """
        themes = data.get("themes")
        if not isinstance(themes, list):
            return ["AI response 'themes' must be a list."]

        overall_summary = data.get("overall_summary")
        errors: list[str] = []
        # Absence is tolerated -- default_summary() covers it -- but a
        # non-string would reach the caller as a rendered summary.
        if overall_summary is not None and not isinstance(overall_summary, str):
            errors.append("AI response 'overall_summary' must be a string.")

        known_codes = {
            entry.get("course_code")
            for entry in self.build_student_context(student_profile)["comments_by_course"]
            if entry.get("course_code")
        }

        for index, theme in enumerate(themes):
            label = f"themes[{index}]"
            if not isinstance(theme, dict):
                errors.append(f"{label} must be a JSON object.")
                continue

            for field_name in ("theme", "summary"):
                if not isinstance(theme.get(field_name), str):
                    errors.append(f"{label}.{field_name} must be a string.")

            category = theme.get("category")
            if category not in self.valid_categories:
                expected = "|".join(sorted(self.valid_categories))
                errors.append(f"{label}.category must be one of: {expected}.")

            references = theme.get("supporting_references")
            if not isinstance(references, list):
                errors.append(f"{label}.supporting_references must be a list.")
                continue

            for ref_index, reference in enumerate(references):
                ref_label = f"{label}.supporting_references[{ref_index}]"
                if not isinstance(reference, dict):
                    errors.append(f"{ref_label} must be a JSON object.")
                    continue
                for field_name in ("course_code", "course_name", "paraphrase"):
                    if not isinstance(reference.get(field_name), str):
                        errors.append(f"{ref_label}.{field_name} must be a string.")
                course_code = reference.get("course_code")
                if isinstance(course_code, str) and course_code not in known_codes:
                    errors.append(
                        f"{ref_label}.course_code '{course_code}' is not a course this "
                        "student has professor comments from."
                    )

        return errors

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
