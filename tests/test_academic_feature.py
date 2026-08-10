from GradusIQ_career.ai.types import AIResponse
from GradusIQ_career.features import run_career_feature
from GradusIQ_career.features.academic import AcademicRunner
from GradusIQ_career.features.orchestrator import DEFAULT_CAREER_FEATURES, run_feature


class FakeClient:
    def __init__(self, text):
        self.text = text
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        return AIResponse(text=self.text, raw={"choices": []}, model="fake-model")


def sample_student_with_comments():
    return {
        "student": {
            "id": 603,
            "name": "Ethan Brooks",
            "major_current": "Mechanical Engineering",
        },
        "courses": [
            {"id": 3010, "name": "Engineering Lab I: Computation", "course_code": "ENGR 102"},
            {"id": 3020, "name": "Calculus I", "course_code": "MATH 151"},
        ],
        "assignments": [
            {"id": 5016, "name": "Python Programming Lab", "course_id": 3010},
            {"id": 5017, "name": "Final Computational Project", "course_id": 3010},
            {"id": 5030, "name": "Midterm Exam", "course_id": 3020},
        ],
        "submissions": [
            {
                "assignment_id": 5016,
                "user_id": 603,
                "submission_comments": [
                    {
                        "id": 57160,
                        "author_id": 1,
                        "author_name": "Dr. Patel",
                        "comment": "Code works — add comments explaining your logic.",
                        "created_at": "2026-02-12T10:00:00Z",
                    }
                ],
            },
            {
                "assignment_id": 5017,
                "user_id": 603,
                "submission_comments": [
                    {
                        "id": 57170,
                        "author_id": 1,
                        "author_name": "Dr. Patel",
                        "comment": "Solid project; document your testing process next time.",
                        "created_at": "2026-04-25T10:00:00Z",
                    }
                ],
            },
            {
                "assignment_id": 5030,
                "user_id": 603,
                "submission_comments": [
                    {
                        "id": 57180,
                        "author_id": 2,
                        "author_name": "Dr. Castillo",
                        "comment": "Strong grasp of derivatives; watch your algebra on exams.",
                        "created_at": "2026-03-01T10:00:00Z",
                    }
                ],
            },
        ],
    }


def sample_student_without_comments():
    return {
        "student": {"id": 999, "name": "No Comments Yet"},
        "courses": [{"id": 4000, "name": "Intro Seminar", "course_code": "UNIV 101"}],
        "assignments": [{"id": 6000, "name": "Welcome Quiz", "course_id": 4000}],
        "submissions": [],
    }


def sample_student_with_submissions_but_no_comments():
    """Submissions exist and are graded, but no professor left feedback."""
    return {
        "student": {"id": 998, "name": "Graded But Silent"},
        "courses": [{"id": 4100, "name": "Intro Seminar", "course_code": "UNIV 101"}],
        "assignments": [{"id": 6100, "name": "Welcome Quiz", "course_id": 4100}],
        "submissions": [
            {"assignment_id": 6100, "user_id": 998, "score": 95, "grade": "A"},
            {
                "assignment_id": 6100,
                "user_id": 998,
                "score": 88,
                "grade": "B+",
                "submission_comments": [],
            },
        ],
    }


def test_academic_success_with_mocked_ai_json():
    client = FakeClient(
        """
        {
          "summary": "Professors consistently praise your work but want more documentation.",
          "data": {
            "themes": [
              {
                "theme": "Documentation habits",
                "category": "concern",
                "summary": "Multiple professors want clearer written explanations of your work.",
                "supporting_references": [
                  {
                    "course_code": "ENGR 102",
                    "course_name": "Engineering Lab I: Computation",
                    "paraphrase": "Asked for more explanation of code logic."
                  }
                ]
              }
            ],
            "overall_summary": "You do strong work but should document your process more."
          }
        }
        """
    )

    result = AcademicRunner(client=client).run(sample_student_with_comments())

    assert result["feature"] == "PROFESSOR_COMMENTS"
    assert result["status"] == "success"
    assert result["summary"] == "Professors consistently praise your work but want more documentation."
    assert result["data"]["themes"][0]["theme"] == "Documentation habits"
    assert result["data"]["overall_summary"].startswith("You do strong work")

    # The whole point of the base.py role fix: this must be "academic", not "career".
    assert client.calls[0]["role"] == "academic"
    assert client.calls[0]["role"] != "career"
    assert "ACADEMIC Prompt" in client.calls[0]["messages"][1]["content"]


def test_academic_build_student_context_groups_comments_by_course():
    runner = AcademicRunner(client=FakeClient('{"data": {}}'))
    context = runner.build_student_context(sample_student_with_comments())

    courses = {entry["course_code"]: entry for entry in context["comments_by_course"]}
    assert set(courses) == {"ENGR 102", "MATH 151"}
    assert len(courses["ENGR 102"]["comments"]) == 2
    assert len(courses["MATH 151"]["comments"]) == 1
    assert courses["MATH 151"]["comments"][0]["author_name"] == "Dr. Castillo"


def test_academic_skips_when_no_submissions():
    client = FakeClient('{"data": {}}')

    result = AcademicRunner(client=client).run(sample_student_without_comments())

    assert result["feature"] == "PROFESSOR_COMMENTS"
    assert result["status"] == "skipped"
    assert result["summary"] == "Missing required fields for this feature."
    assert result["errors"]
    assert client.calls == []


def test_academic_skips_when_submissions_exist_but_carry_no_comments():
    """Fix 1: the required_paths proxy alone would let this through.

    `submissions` is non-empty, so find_missing_fields is satisfied, but there
    is not a single comment to analyze. Sending comments_by_course: [] to the
    model invites invention; skip instead, reusing the same skip result the
    missing-submissions case produces.
    """
    client = FakeClient('{"data": {"themes": []}}')

    result = AcademicRunner(client=client).run(
        sample_student_with_submissions_but_no_comments()
    )

    assert result["feature"] == "PROFESSOR_COMMENTS"
    assert result["status"] == "skipped"
    assert result["summary"] == "Missing required fields for this feature."
    assert result["errors"] == [
        "Missing required field: submissions[].submission_comments"
    ]
    assert client.calls == []


def test_academic_still_runs_for_students_who_do_have_comments():
    """Fix 1 must not change the behavior of the populated (demo) case."""
    client = FakeClient('{"summary": "done", "data": {"themes": []}}')

    result = AcademicRunner(client=client).run(sample_student_with_comments())

    assert result["status"] == "success"
    assert len(client.calls) == 1


def test_academic_empty_data_object_is_a_contract_violation():
    """Fix 2: valid JSON, no themes key -- previously returned success."""
    client = FakeClient('{"summary": "looks fine", "data": {}}')

    result = AcademicRunner(client=client).run(sample_student_with_comments())

    assert result["feature"] == "PROFESSOR_COMMENTS"
    assert result["status"] == "failed"
    assert result["data"] == {}
    assert result["errors"] == ["AI response 'themes' must be a list."]


def test_academic_invalid_theme_category_is_rejected():
    """Fix 2: category outside strength|concern|praise|flag."""
    client = FakeClient(
        """
        {
          "data": {
            "themes": [
              {
                "theme": "Documentation habits",
                "category": "very bad",
                "summary": "Professors want clearer explanations.",
                "supporting_references": [
                  {
                    "course_code": "ENGR 102",
                    "course_name": "Engineering Lab I: Computation",
                    "paraphrase": "Asked for more explanation of code logic."
                  }
                ]
              }
            ],
            "overall_summary": "Document more."
          }
        }
        """
    )

    result = AcademicRunner(client=client).run(sample_student_with_comments())

    assert result["status"] == "failed"
    assert result["data"] == {}
    assert result["errors"] == [
        "themes[0].category must be one of: concern|flag|praise|strength."
    ]


def test_academic_malformed_theme_fields_are_rejected():
    """Fix 2: right keys, wrong types, and a non-list supporting_references."""
    client = FakeClient(
        """
        {
          "data": {
            "themes": [
              {
                "theme": 42,
                "category": "concern",
                "summary": null,
                "supporting_references": "ENGR 102"
              }
            ]
          }
        }
        """
    )

    result = AcademicRunner(client=client).run(sample_student_with_comments())

    assert result["status"] == "failed"
    assert result["errors"] == [
        "themes[0].theme must be a string.",
        "themes[0].summary must be a string.",
        "themes[0].supporting_references must be a list.",
    ]


def test_academic_hallucinated_citation_is_rejected():
    """Fix 3: a well-formed citation to a course with no comments.

    PHYS 208 is not among the courses this student has professor comments
    from (ENGR 102 and MATH 151), so the reference cannot be supported by
    anything the model was shown.
    """
    client = FakeClient(
        """
        {
          "data": {
            "themes": [
              {
                "theme": "Lab technique",
                "category": "praise",
                "summary": "Professors consistently praise your lab work.",
                "supporting_references": [
                  {
                    "course_code": "ENGR 102",
                    "course_name": "Engineering Lab I: Computation",
                    "paraphrase": "Noted your code worked as intended."
                  },
                  {
                    "course_code": "PHYS 208",
                    "course_name": "Electricity and Optics",
                    "paraphrase": "Praised your experimental setup."
                  }
                ]
              }
            ],
            "overall_summary": "Strong lab work."
          }
        }
        """
    )

    result = AcademicRunner(client=client).run(sample_student_with_comments())

    assert result["status"] == "failed"
    assert result["data"] == {}
    assert result["errors"] == [
        "themes[0].supporting_references[1].course_code 'PHYS 208' is not a "
        "course this student has professor comments from."
    ]


def test_academic_accepts_citations_to_real_commented_courses():
    """Fix 3 must not reject legitimate citations."""
    client = FakeClient(
        """
        {
          "data": {
            "themes": [
              {
                "theme": "Documentation habits",
                "category": "concern",
                "summary": "Professors want clearer written explanations.",
                "supporting_references": [
                  {
                    "course_code": "ENGR 102",
                    "course_name": "Engineering Lab I: Computation",
                    "paraphrase": "Asked for more explanation of code logic."
                  },
                  {
                    "course_code": "MATH 151",
                    "course_name": "Calculus I",
                    "paraphrase": "Flagged algebra slips on exams."
                  }
                ]
              }
            ],
            "overall_summary": "Document your process more."
          }
        }
        """
    )

    result = AcademicRunner(client=client).run(sample_student_with_comments())

    assert result["status"] == "success"
    assert result["errors"] == []
    assert result["data"]["themes"][0]["theme"] == "Documentation habits"


def test_academic_malformed_ai_json_returns_failed_result():
    client = FakeClient("{not-json")

    result = AcademicRunner(client=client).run(sample_student_with_comments())

    assert result["feature"] == "PROFESSOR_COMMENTS"
    assert result["status"] == "failed"
    assert result["data"] == {}
    assert "JSON" in result["errors"][0] or "object" in result["errors"][0]


def test_academic_missing_prompt_file_is_handled_clearly(tmp_path):
    missing_prompt = tmp_path / "missing_prompt.md"
    client = FakeClient('{"data": {}}')

    result = AcademicRunner(client=client, prompt_path=missing_prompt).run(
        sample_student_with_comments()
    )

    assert result["feature"] == "PROFESSOR_COMMENTS"
    assert result["status"] == "failed"
    assert "Prompt file not found" in result["errors"][0]
    assert client.calls == []


def test_orchestrator_run_feature_resolves_professor_comments():
    client = FakeClient('{"summary": "done", "data": {"themes": []}}')

    result = run_feature("PROFESSOR_COMMENTS", sample_student_with_comments(), client)

    assert result["feature"] == "PROFESSOR_COMMENTS"
    assert result["status"] == "success"
    assert client.calls[0]["role"] == "academic"


def test_init_run_career_feature_resolves_professor_comments():
    client = FakeClient('{"summary": "done", "data": {"themes": []}}')

    result = run_career_feature("PROFESSOR_COMMENTS", sample_student_with_comments(), client)

    assert result["feature"] == "PROFESSOR_COMMENTS"
    assert result["status"] == "success"
    assert client.calls[0]["role"] == "academic"


def test_professor_comments_is_opt_in_not_in_default_career_features():
    assert "PROFESSOR_COMMENTS" not in DEFAULT_CAREER_FEATURES
    assert DEFAULT_CAREER_FEATURES == ("FIT", "GAP", "SHIFT")
