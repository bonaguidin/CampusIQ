from CampusIQ_career.ai.types import AIResponse
from CampusIQ_career.features import run_career_feature
from CampusIQ_career.features.academic import AcademicRunner
from CampusIQ_career.features.orchestrator import DEFAULT_CAREER_FEATURES, run_feature


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
