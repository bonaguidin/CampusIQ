from copy import deepcopy

import pytest

from CampusIQ_career.ai.types import AIResponse
from CampusIQ_career.features import run_career_feature
from CampusIQ_career.features.fit import FitRunner
from CampusIQ_career.features.gap import GapRunner
from CampusIQ_career.features.shift import ShiftRunner


class FakeClient:
    def __init__(self, text):
        self.text = text
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        return AIResponse(text=self.text, raw={"choices": []}, model="fake-model")


def sample_student():
    return {
        "student": {
            "id": 601,
            "name": "Jordan Reyes",
            "major_current": "Business Administration",
            "major_intended": "Finance",
            "classification": "Freshman",
            "expected_graduation": "2029-05",
        },
        "career": {
            "target_roles": ["Business Analyst Intern", "Operations Intern"],
            "interests": ["operations", "finance", "analytics"],
            "career_goals": "Explore business internships.",
            "geographic_preference": "DFW metro preferred",
            "ai_anxiety_level": "moderate",
            "skills_self_reported": {
                "technical": ["Excel", "PowerPoint"],
                "soft": ["communication", "team collaboration"],
                "ai_exposure": "informal AI study support",
            },
            "certifications": [],
            "work_experience": [
                {
                    "employer": "Mays Business School",
                    "role": "Case Team Member",
                    "duration": "Spring 2026",
                }
            ],
            "projects": [
                {
                    "name": "Market Brief",
                    "description": "Prepared customer and competitor analysis.",
                }
            ],
        },
        "courses": [
            {
                "course_code": "BUSN 101",
                "name": "Freshman Business Initiative",
            }
        ],
    }


def test_fit_success_with_mocked_ai_json():
    client = FakeClient(
        """
        {
          "summary": "You have two realistic role directions.",
          "data": {
            "role_matches": [
              {
                "role": "Business Analyst Intern",
                "fit_level": "medium",
                "rationale": "Excel and business coursework align.",
                "supporting_signals": ["Excel", "business case project"],
                "missing_signals": ["SQL"]
              }
            ],
            "overall_fit_summary": "Business analyst is a moderate fit."
          }
        }
        """
    )

    result = FitRunner(client=client).run(sample_student())

    assert result["feature"] == "FIT"
    assert result["status"] == "success"
    assert result["summary"] == "You have two realistic role directions."
    assert result["data"]["role_matches"][0]["role"] == "Business Analyst Intern"
    assert client.calls[0]["role"] == "career"
    assert "FIT Prompt" in client.calls[0]["messages"][1]["content"]


def test_gap_success_with_mocked_ai_json():
    client = FakeClient(
        """
        {
          "summary": "Your main readiness gap is analytics depth.",
          "data": {
            "readiness_score": 6,
            "strengths": ["Excel", "presentation"],
            "must_have_gaps": ["SQL"],
            "nice_to_have_gaps": ["dashboarding"],
            "recommended_next_steps": ["Build a small SQL project"]
          }
        }
        """
    )

    result = GapRunner(client=client).run(sample_student())

    assert result["feature"] == "GAP"
    assert result["status"] == "success"
    assert result["data"]["readiness_score"] == 6
    assert client.calls[0]["role"] == "career"
    assert "GAP Prompt" in client.calls[0]["messages"][1]["content"]


def test_shift_success_with_mocked_ai_json():
    client = FakeClient(
        """
        {
          "summary": "Your target roles are shifting toward AI-assisted analysis.",
          "data": {
            "role_evolution_summary": "Business roles increasingly expect AI-assisted analysis.",
            "task_shifts": ["first-pass spreadsheet analysis"],
            "durable_skills": ["judgment", "communication"],
            "adjacent_paths": ["operations analytics"],
            "ai_fluency_guidance": ["Describe how you use AI to check assumptions"]
          }
        }
        """
    )

    result = ShiftRunner(client=client).run(sample_student())

    assert result["feature"] == "SHIFT"
    assert result["status"] == "success"
    assert result["data"]["durable_skills"] == ["judgment", "communication"]
    assert client.calls[0]["role"] == "career"
    assert "SHIFT Prompt" in client.calls[0]["messages"][1]["content"]


@pytest.mark.parametrize(
    ("runner_class", "feature", "remove_path"),
    [
        (FitRunner, "FIT", ("career", "target_roles")),
        (GapRunner, "GAP", ("student", "expected_graduation")),
        (ShiftRunner, "SHIFT", ("career", "skills_self_reported")),
    ],
)
def test_runner_skips_when_required_fields_are_missing(runner_class, feature, remove_path):
    student = sample_student()
    parent = student[remove_path[0]]
    parent.pop(remove_path[1])
    client = FakeClient('{"data": {}}')

    result = runner_class(client=client).run(student)

    assert result["feature"] == feature
    assert result["status"] == "skipped"
    assert result["summary"] == "Missing required fields for this feature."
    assert result["errors"]
    assert client.calls == []


def test_malformed_ai_json_returns_failed_result():
    client = FakeClient("{not-json")

    result = FitRunner(client=client).run(sample_student())

    assert result["feature"] == "FIT"
    assert result["status"] == "failed"
    assert result["data"] == {}
    assert "JSON" in result["errors"][0] or "object" in result["errors"][0]


def test_missing_prompt_file_is_handled_clearly(tmp_path):
    missing_prompt = tmp_path / "missing_prompt.md"
    client = FakeClient('{"data": {}}')

    result = FitRunner(client=client, prompt_path=missing_prompt).run(sample_student())

    assert result["feature"] == "FIT"
    assert result["status"] == "failed"
    assert "Prompt file not found" in result["errors"][0]
    assert client.calls == []


@pytest.mark.parametrize(
    ("feature_name", "expected_runner"),
    [
        ("FIT", "FIT"),
        ("gap", "GAP"),
        ("Shift", "SHIFT"),
    ],
)
def test_run_career_feature_helper(feature_name, expected_runner):
    client = FakeClient('{"summary": "done", "data": {}}')

    result = run_career_feature(feature_name, sample_student(), client)

    assert result["feature"] == expected_runner
    assert result["status"] == "success"
    assert client.calls[0]["role"] == "career"


def test_run_career_feature_rejects_invalid_feature():
    with pytest.raises(ValueError, match="Unsupported career feature"):
        run_career_feature("ACADEMIC", sample_student(), FakeClient('{"data": {}}'))


def test_test_student_factory_is_isolated_between_tests():
    first = sample_student()
    second = deepcopy(first)

    first["career"]["target_roles"].append("Changed")

    assert second["career"]["target_roles"] == ["Business Analyst Intern", "Operations Intern"]
