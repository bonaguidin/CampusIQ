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
    # Operations Intern (13-1199.00) is the only demo role that reaches the
    # agent: no O*NET ratings AND no related occupations to borrow from.
    # Finance Intern used to qualify, but now borrows from a rated neighbour.
    agent_data = _live_agent_requirements()
    monkeypatch.setattr(
        gap_module.role_research_agent,
        "get_role_requirements",
        lambda role: agent_data if role == "Operations Intern" else None,
    )

    result = GapRunner(client=FakeClient("{}")).role_requirements_for(["Operations Intern"])
    entry = result["Operations Intern"]

    # soc_code/soc_title always come from the static file, never the agent.
    assert entry["soc_code"] == "13-1199.00"
    assert entry["soc_title"] == "Business Operations Specialists, All Other"
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
    # Operations Intern reaches the agent and its research wins; Business
    # Analyst Intern has its own O*NET ratings so the agent never runs and it
    # keeps the static certification lists.
    agent_data = _live_agent_requirements()
    monkeypatch.setattr(
        gap_module.role_research_agent,
        "get_role_requirements",
        lambda role: agent_data if role == "Operations Intern" else None,
    )

    result = GapRunner(client=FakeClient("{}")).role_requirements_for(
        ["Operations Intern", "Business Analyst Intern"]
    )

    assert result["Operations Intern"]["soc_code"] == "13-1199.00"
    assert result["Operations Intern"]["must_have_skills"] == ["Live-researched must-have skill"]
    assert result["Business Analyst Intern"]["soc_code"] == "13-1111.00"
    assert result["Business Analyst Intern"]["requirements_source"] == "static"
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
        ["Business Analyst Intern", "Finance Intern", "Operations Intern"]
    )

    # 13-1111.00 has its own ratings -> skipped. 13-2051.00 borrows from a rated
    # neighbour -> also skipped. Only 13-1199.00, with neither, is researched.
    assert called == ["Operations Intern"]
    assert result["Business Analyst Intern"]["requirements_source"] == "static"
    assert result["Finance Intern"]["requirements_source"] == "static"
    assert result["Operations Intern"]["requirements_source"] == "agent"


def test_gap_context_marks_agent_filled_roles_with_agent_provenance(monkeypatch):
    monkeypatch.setattr(
        gap_module.role_research_agent,
        "get_role_requirements",
        lambda role: _live_agent_requirements() if role == "Operations Intern" else None,
    )
    student = sample_student()
    student["career"]["target_roles"] = ["Business Analyst Intern", "Finance Intern", "Operations Intern"]

    context = GapRunner(client=FakeClient("{}")).build_student_context(student)
    by_role = context["market_requirements"]["by_role"]

    assert by_role["Business Analyst Intern"]["provenance"] == "onet"
    # Borrowed from a rated neighbour, so never reached the agent.
    assert by_role["Finance Intern"]["provenance"] == "onet_neighbor"
    # Upgraded from "none" because the agent supplied this role's requirements.
    assert by_role["Operations Intern"]["provenance"] == "agent"


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


# ---------------------------------------------------------------- SHIFT grounding
# SHIFT used to send the model nothing but student self-report, so every
# role-specific claim was recall. These cover the two blocks that replaced that.

def test_shift_signals_ground_adjacent_paths_tools_and_tasks():
    from CampusIQ_career.features.market_data import get_shift_signals

    signals = get_shift_signals(["Business Analyst Intern"])
    entry = signals["by_role"]["Business Analyst Intern"]

    assert entry["soc_code"] == "13-1111.00"
    assert entry["grounded"] is True
    # Five Primary-Short related occupations, each with a resolved title --
    # this is what adjacent_paths must be drawn from instead of invented.
    assert len(entry["related"]) == 5
    assert all(r["soc"] and r["title"] for r in entry["related"])
    assert entry["hot_software"]
    assert entry["core_tasks"]


def test_shift_signals_survive_an_occupation_with_no_ratings():
    """Finance Intern has no O*NET importance scores but does have tools.

    SHIFT consumes tools/tasks/neighbours, not ratings, so it stays grounded
    for a role GAP has to fall back to the research agent for.
    """
    from CampusIQ_career.features.market_data import get_shift_signals

    entry = get_shift_signals(["Finance Intern"])["by_role"]["Finance Intern"]

    assert entry["soc_code"] == "13-2051.00"
    assert entry["hot_software"]
    assert entry["grounded"] is True


def test_shift_context_carries_both_grounding_blocks(monkeypatch):
    from CampusIQ_career.features import shift as shift_module

    trends = {
        "role_evolution": "Shifting toward validating model output.",
        "task_shifts": ["Routine variance analysis is increasingly automated"],
        "emerging_skills": ["Prompt-assisted modeling"],
        "sources": ["https://example.org/report"],
    }
    monkeypatch.setattr(
        shift_module.role_research_agent,
        "get_role_trends",
        lambda role, client=None: trends if role == "Business Analyst Intern" else None,
    )
    student = sample_student()
    student["career"]["target_roles"] = ["Business Analyst Intern", "Operations Intern"]

    context = ShiftRunner(client=FakeClient("{}")).build_student_context(student)

    assert context["shift_signals"]["by_role"]["Business Analyst Intern"]["grounded"] is True
    assert context["role_trends"]["Business Analyst Intern"] == trends
    # A role research missed is named, not silently absent -- the prompt keys
    # off this to stay generic instead of improvising a trend.
    assert context["role_trends"]["_unresearched_roles"] == ["Operations Intern"]


def test_shift_reports_every_role_when_trend_research_is_unavailable(monkeypatch):
    from CampusIQ_career.features import shift as shift_module

    monkeypatch.setattr(
        shift_module.role_research_agent, "get_role_trends", lambda role, client=None: None
    )
    student = sample_student()
    student["career"]["target_roles"] = ["Business Analyst Intern"]

    context = ShiftRunner(client=FakeClient("{}")).build_student_context(student)

    assert context["role_trends"] == {"_unresearched_roles": ["Business Analyst Intern"]}
    # Local O*NET grounding is unaffected by the research outage.
    assert context["shift_signals"]["by_role"]["Business Analyst Intern"]["related"]


def test_shift_researches_roles_concurrently_not_serially():
    """Wall time must track the slowest role, not the sum of all of them.

    Serial research put a three-role student at ~2m43s against the frontend
    proxy's 300s ceiling; this is the property that keeps that from regressing.
    """
    import time
    from CampusIQ_career.features import shift as shift_module

    def slow(role, client=None):
        time.sleep(0.4)
        return {"role_evolution": role, "task_shifts": [], "emerging_skills": [], "sources": []}

    original = shift_module.role_research_agent.get_role_trends
    shift_module.role_research_agent.get_role_trends = slow
    try:
        started = time.monotonic()
        result = ShiftRunner(client=FakeClient("{}")).role_trends_for(["A", "B", "C"])
        elapsed = time.monotonic() - started
    finally:
        shift_module.role_research_agent.get_role_trends = original

    assert set(result) == {"A", "B", "C"}
    # Serial would be >=1.2s; concurrent lands near a single 0.4s sleep.
    assert elapsed < 0.9, f"looks serial: {elapsed:.2f}s for 3 x 0.4s lookups"


def test_shift_duplicate_roles_are_researched_once(monkeypatch):
    from CampusIQ_career.features import shift as shift_module

    calls: list[str] = []

    def spy(role, client=None):
        calls.append(role)
        return {"role_evolution": role, "task_shifts": [], "emerging_skills": [], "sources": []}

    monkeypatch.setattr(shift_module.role_research_agent, "get_role_trends", spy)
    result = ShiftRunner(client=FakeClient("{}")).role_trends_for(["Finance Intern", "Finance Intern"])

    assert calls == ["Finance Intern"]
    assert set(result) == {"Finance Intern"}


def test_shift_one_failing_role_does_not_abort_the_others(monkeypatch):
    from CampusIQ_career.features import shift as shift_module

    def flaky(role, client=None):
        if role == "B":
            raise RuntimeError("upstream blew up")
        return {"role_evolution": role, "task_shifts": [], "emerging_skills": [], "sources": []}

    monkeypatch.setattr(shift_module.role_research_agent, "get_role_trends", flaky)
    result = ShiftRunner(client=FakeClient("{}")).role_trends_for(["A", "B", "C"])

    assert set(result) == {"A", "C", "_unresearched_roles"}
    assert result["_unresearched_roles"] == ["B"]


# ---------------------------------------------------------------- score range
# A live run returned readiness_score 0.32 for a student whose roles mostly
# lacked O*NET data. It passed every check -- api.py's _matches_contract only
# asks "is it a number" -- and GapAnalysisPanel renders the raw value next to
# "/ 10", so the student would have seen "0.32".

def _gap_response(score):
    return (
        '{"summary": "s", "data": {"readiness_score": ' + score + ','
        '"strengths": [], "must_have_gaps": [], "nice_to_have_gaps": [],'
        '"recommended_next_steps": []}}'
    )


@pytest.mark.parametrize("bad", ["0.32", "7.5", "70", "-1", '"6"', "true"])
def test_gap_rejects_out_of_scale_readiness_score(bad):
    result = GapRunner(client=FakeClient(_gap_response(bad))).run(sample_student())

    assert result["status"] == "failed"
    assert result["data"] == {}
    assert "readiness_score" in result["errors"][0]


@pytest.mark.parametrize("good", ["0", "7", "10", "7.0"])
def test_gap_accepts_whole_numbers_on_the_zero_to_ten_scale(good):
    result = GapRunner(client=FakeClient(_gap_response(good))).run(sample_student())

    assert result["status"] == "success"


def test_gap_tolerates_a_missing_readiness_score():
    """Absence renders as nothing; a wrong value renders as a falsehood.

    Only the second is what the range guard exists to stop, so a payload
    without the key must still succeed.
    """
    client = FakeClient('{"summary": "s", "data": {"strengths": []}}')

    assert GapRunner(client=client).run(sample_student())["status"] == "success"


# ------------------------------------------------------- neighbour borrowing
# O*NET has never rated 122 of its 1,016 occupations. 29 of those have a rated
# occupation in their Primary-Short related list, so borrowing beats live web
# research there: instant, free, and traceable to a named occupation. The
# condition is disclosure -- these are a NEIGHBOUR's scores.

def test_unrated_role_borrows_from_its_nearest_rated_neighbour():
    from CampusIQ_career.features.market_data import get_market_requirements

    entry = get_market_requirements(["Finance Intern"])["by_role"]["Finance Intern"]

    assert entry["provenance"] == "onet_neighbor"
    assert entry["borrowed_from"]["soc"] == "13-2052.00"
    assert entry["requirements"]["skills"], "borrowed ratings should be populated"
    assert entry["matched"] is True


def test_borrowing_keeps_the_targets_own_software_not_the_neighbours():
    """Only ratings are borrowed.

    Finance Intern has 33 hot technologies of its own despite having no
    ratings; swapping the whole entry would discard real data for a
    neighbour's.
    """
    from CampusIQ_career.features.market_data import get_market_requirements

    finance = get_market_requirements(["Finance Intern"])["by_role"]["Finance Intern"]
    neighbour = get_market_requirements(["Business Analyst Intern"])["by_role"]

    assert finance["soc_code"] == "13-2051.00"  # still the target's own SOC
    assert finance["hot_software"]
    assert finance["soc_title"] == "Financial and Investment Analysts"


def test_borrowing_is_disclosed_in_notes():
    from CampusIQ_career.features.market_data import get_market_requirements

    notes = " ".join(get_market_requirements(["Finance Intern"])["notes"])

    assert "borrowed" in notes.lower()
    assert "13-2052.00" in notes
    assert "disclosed" in notes.lower()


def test_role_with_no_rated_neighbour_still_falls_through_to_research():
    from CampusIQ_career.features.market_data import get_market_requirements

    entry = get_market_requirements(["Operations Intern"])["by_role"]["Operations Intern"]

    # 13-1199.00 has no related occupations at all in the release.
    assert entry["provenance"] == "none"
    assert entry["borrowed_from"] is None


def test_agent_is_not_called_for_a_role_that_borrowed_from_a_neighbour(monkeypatch):
    """Borrowing must pre-empt research, not run alongside it."""
    called: list[str] = []
    monkeypatch.setattr(
        gap_module.role_research_agent,
        "get_role_requirements",
        lambda role: called.append(role) or None,
    )

    GapRunner(client=FakeClient("{}")).role_requirements_for(
        ["Finance Intern", "Operations Intern"]
    )

    assert called == ["Operations Intern"]
