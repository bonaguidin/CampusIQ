from copy import deepcopy

import pytest

from CampusIQ_career.ai.types import AIResponse
from CampusIQ_career.features import gap as gap_module
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


_GAP_SUCCESS_JSON = """
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


def _live_agent_requirements():
    # soc_code/soc_title are deliberately implausible/unlike the static
    # entry -- their presence here proves they're discarded, not just
    # coincidentally matching.
    return {
        "soc_code": "13-1111.00-LIVE",
        "soc_title": "Live-Researched Management Analysts",
        "must_have_skills": ["Live-researched must-have skill"],
        "nice_to_have_skills": [],
        "must_have_certifications": [],
        "nice_to_have_certifications": [],
    }


def test_role_requirements_for_uses_agent_skills_but_static_soc_code(monkeypatch):
    # Finance Intern (13-2051.00) is one of the two demo roles O*NET has no
    # ratings for, so it is a role the agent actually runs for. A role with
    # O*NET coverage would skip the agent entirely -- see
    # test_agent_is_not_called_for_roles_onet_already_rates.
    agent_data = _live_agent_requirements()
    monkeypatch.setattr(
        gap_module.role_research_agent,
        "get_role_requirements",
        lambda role: agent_data if role == "Finance Intern" else None,
    )

    result = GapRunner(client=FakeClient("{}")).role_requirements_for(["Finance Intern"])
    entry = result["Finance Intern"]

    # soc_code/soc_title always come from the static file, never the agent.
    assert entry["soc_code"] == "13-2051.00"
    assert entry["soc_title"] == "Financial and Investment Analysts"
    # must_have_skills comes from the agent (non-empty agent list wins).
    assert entry["must_have_skills"] == ["Live-researched must-have skill"]
    assert entry["requirements_source"] == "agent"


def test_role_requirements_for_agent_empty_list_does_not_clobber_populated_static_list(monkeypatch):
    # Operations Intern's static entry has a non-empty
    # nice_to_have_certifications; an agent result with an empty list for
    # that field must not blank it out.
    agent_data = dict(_live_agent_requirements(), nice_to_have_certifications=[])
    monkeypatch.setattr(gap_module.role_research_agent, "get_role_requirements", lambda role: agent_data)

    result = GapRunner(client=FakeClient("{}")).role_requirements_for(["Operations Intern"])
    entry = result["Operations Intern"]

    assert entry["nice_to_have_certifications"] == ["Six Sigma Yellow Belt"]
    assert entry["must_have_skills"] == ["Live-researched must-have skill"]  # agent's non-empty list still wins
    assert entry["requirements_source"] == "agent"


def test_role_requirements_for_falls_back_to_static_when_agent_returns_none(monkeypatch):
    monkeypatch.setattr(gap_module.role_research_agent, "get_role_requirements", lambda role: None)

    result = GapRunner(client=FakeClient("{}")).role_requirements_for(["Business Analyst Intern"])

    assert result["Business Analyst Intern"]["soc_code"] == "13-1111.00"
    assert "Excel modeling" in result["Business Analyst Intern"]["must_have_skills"]
    assert result["Business Analyst Intern"]["requirements_source"] == "static"


def test_gap_run_produces_identical_feature_result_shape_regardless_of_role_requirements_source(monkeypatch):
    monkeypatch.setattr(
        gap_module.role_research_agent,
        "get_role_requirements",
        lambda role: _live_agent_requirements() if role == "Business Analyst Intern" else None,
    )
    agent_result = GapRunner(client=FakeClient(_GAP_SUCCESS_JSON)).run(sample_student())

    monkeypatch.setattr(gap_module.role_research_agent, "get_role_requirements", lambda role: None)
    fallback_result = GapRunner(client=FakeClient(_GAP_SUCCESS_JSON)).run(sample_student())

    assert agent_result.keys() == fallback_result.keys()
    assert agent_result["status"] == fallback_result["status"] == "success"
    assert agent_result["data"] == fallback_result["data"]
    assert agent_result["summary"] == fallback_result["summary"]


def test_role_requirements_for_reports_unmatched_when_agent_and_static_both_miss(monkeypatch):
    monkeypatch.setattr(gap_module.role_research_agent, "get_role_requirements", lambda role: None)

    result = GapRunner(client=FakeClient("{}")).role_requirements_for(["Quantum Widget Intern"])

    assert result == {"_unmatched_roles": ["Quantum Widget Intern"]}


def test_role_requirements_for_handles_mixed_agent_and_static_results_across_roles(monkeypatch):
    # Finance Intern has no O*NET ratings so the agent runs and wins; Operations
    # Intern also has none but the agent misses, so it falls back to static.
    agent_data = _live_agent_requirements()
    monkeypatch.setattr(
        gap_module.role_research_agent,
        "get_role_requirements",
        lambda role: agent_data if role == "Finance Intern" else None,
    )

    result = GapRunner(client=FakeClient("{}")).role_requirements_for(
        ["Finance Intern", "Operations Intern"]
    )

    assert result["Finance Intern"]["soc_code"] == "13-2051.00"
    assert result["Finance Intern"]["must_have_skills"] == ["Live-researched must-have skill"]
    assert result["Operations Intern"]["soc_code"] == "13-1199.00"
    assert result["Operations Intern"]["requirements_source"] == "static"
    assert "_unmatched_roles" not in result


def test_agent_is_not_called_for_roles_onet_already_rates(monkeypatch):
    """The core of the gap-fill change: research is spent only where it is needed.

    The agent used to run for every role while the prompt forbade using its
    skill lists wherever O*NET data existed -- research paid for and discarded.
    """
    called: list[str] = []

    def _spy(role):
        called.append(role)
        return _live_agent_requirements()

    monkeypatch.setattr(gap_module.role_research_agent, "get_role_requirements", _spy)

    result = GapRunner(client=FakeClient("{}")).role_requirements_for(
        ["Business Analyst Intern", "Finance Intern"]
    )

    # 13-1111.00 has O*NET ratings -> skipped. 13-2051.00 has none -> researched.
    assert called == ["Finance Intern"]
    assert result["Business Analyst Intern"]["requirements_source"] == "static"
    assert result["Finance Intern"]["requirements_source"] == "agent"


def test_gap_context_marks_agent_filled_roles_with_agent_provenance(monkeypatch):
    monkeypatch.setattr(
        gap_module.role_research_agent,
        "get_role_requirements",
        lambda role: _live_agent_requirements() if role == "Finance Intern" else None,
    )
    student = sample_student()
    student["career"]["target_roles"] = ["Business Analyst Intern", "Finance Intern", "Operations Intern"]

    context = GapRunner(client=FakeClient("{}")).build_student_context(student)
    by_role = context["market_requirements"]["by_role"]

    assert by_role["Business Analyst Intern"]["provenance"] == "onet"
    # Upgraded from "none" because the agent supplied this role's requirements.
    assert by_role["Finance Intern"]["provenance"] == "agent"
    # Agent ran but missed, so nothing grounds this one.
    assert by_role["Operations Intern"]["provenance"] == "none"


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
