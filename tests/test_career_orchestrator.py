from copy import deepcopy

import pytest

from CampusIQ_career.ai.types import AIResponse
from CampusIQ_career.features.orchestrator import run_career_analysis, run_feature


class QueueClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        text = self.responses.pop(0)
        return AIResponse(text=text, raw={"choices": []}, model="fake-model")


def feature_response(feature):
    return f"""
    {{
      "summary": "{feature} completed",
      "data": {{
        "marker": "{feature}"
      }}
    }}
    """


def sample_student():
    return {
        "student": {
            "id": 601,
            "major_current": "Business Administration",
            "major_intended": "Finance",
            "classification": "Freshman",
            "expected_graduation": "2029-05",
        },
        "career": {
            "target_roles": ["Business Analyst Intern"],
            "interests": ["analytics"],
            "ai_anxiety_level": "moderate",
            "skills_self_reported": {
                "technical": ["Excel"],
                "soft": ["communication"],
                "ai_exposure": "informal",
            },
            "work_experience": [
                {
                    "employer": "Mays Business School",
                    "role": "Case Team Member",
                }
            ],
            "projects": [{"name": "Market Brief"}],
            "certifications": [],
        },
    }


def test_run_single_fit():
    client = QueueClient([feature_response("FIT")])

    result = run_feature("FIT", sample_student(), client)

    assert result["feature"] == "FIT"
    assert result["status"] == "success"
    assert result["data"]["marker"] == "FIT"
    assert client.calls[0]["role"] == "career"


def test_run_all_fit_gap_shift():
    client = QueueClient([
        feature_response("FIT"),
        feature_response("GAP"),
        feature_response("SHIFT"),
    ])

    result = run_career_analysis(sample_student(), client)

    assert result["analysis_type"] == "career"
    assert result["status"] == "success"
    assert result["student_id"] == "601"
    assert result["features_requested"] == ["FIT", "GAP", "SHIFT"]
    assert list(result["results"]) == ["FIT", "GAP", "SHIFT"]
    assert len(client.calls) == 3
    assert [call["role"] for call in client.calls] == ["career", "career", "career"]


def test_run_subset_fit_gap_only():
    client = QueueClient([
        feature_response("FIT"),
        feature_response("GAP"),
    ])

    result = run_career_analysis(sample_student(), client, features=["FIT", "gap"])

    assert result["status"] == "success"
    assert result["features_requested"] == ["FIT", "GAP"]
    assert set(result["results"]) == {"FIT", "GAP"}
    assert len(client.calls) == 2


def test_invalid_feature_name_raises_clear_value_error():
    client = QueueClient([])

    with pytest.raises(ValueError, match="Unsupported career feature"):
        run_career_analysis(sample_student(), client, features=["FIT", "ACADEMIC"])

    assert client.calls == []


def test_one_feature_fails_but_others_still_run():
    client = QueueClient([
        feature_response("FIT"),
        "{not-json",
        feature_response("SHIFT"),
    ])

    result = run_career_analysis(sample_student(), client)

    assert result["status"] == "partial_success"
    assert result["results"]["FIT"]["status"] == "success"
    assert result["results"]["GAP"]["status"] == "failed"
    assert result["results"]["SHIFT"]["status"] == "success"
    assert len(client.calls) == 3
    assert result["errors"]


def test_all_skipped_returns_skipped():
    student = sample_student()
    student["career"] = {}
    client = QueueClient([])

    result = run_career_analysis(student, client)

    assert result["status"] == "skipped"
    assert all(item["status"] == "skipped" for item in result["results"].values())
    assert len(client.calls) == 0
    assert result["errors"]


def test_mixed_success_and_skip_returns_partial_success():
    student = sample_student()
    student["career"].pop("ai_anxiety_level")
    client = QueueClient([
        feature_response("FIT"),
        feature_response("GAP"),
    ])

    result = run_career_analysis(student, client)

    assert result["status"] == "partial_success"
    assert result["results"]["FIT"]["status"] == "success"
    assert result["results"]["GAP"]["status"] == "success"
    assert result["results"]["SHIFT"]["status"] == "skipped"
    assert len(client.calls) == 2


def test_all_failed_returns_failed():
    client = QueueClient(["{bad", "{bad", "{bad"])

    result = run_career_analysis(sample_student(), client)

    assert result["status"] == "failed"
    assert all(item["status"] == "failed" for item in result["results"].values())
    assert len(client.calls) == 3
    assert len(result["errors"]) == 3


def test_no_real_api_client_is_constructed():
    student = sample_student()
    original = deepcopy(student)
    client = QueueClient([feature_response("FIT")])

    result = run_career_analysis(student, client, features=["FIT"])

    assert result["status"] == "success"
    assert student == original
    assert len(client.calls) == 1
