import json

import pytest

from GradusIQ_career.ai.types import AIResponse
from GradusIQ_career.demo import build_demo_cache as bdc


SAMPLE_PROFILE = {
    "student": {
        "id": 1,
        "major_current": "Computer Science",
        "major_intended": "Computer Science",
        "classification": "Sophomore",
        "expected_graduation": "2027-05",
    },
    "career": {
        "target_roles": ["Software Engineering Intern"],
        "interests": ["backend systems"],
        "skills_self_reported": {"technical": ["Python", "Git"]},
        "work_experience": [{"employer": "Test Corp", "role": "Intern", "duration": "Summer 2026"}],
        "ai_anxiety_level": "low",
    },
}

FIT_PAYLOAD = {
    "summary": "FIT summary.",
    "data": {
        "role_matches": [
            {
                "role": "Software Engineering Intern",
                "fit_level": "medium",
                "rationale": "Confirmed Python and Git skills are relevant.",
                "supporting_signals": ["Python", "Git"],
                "missing_signals": ["Production experience"],
            }
        ],
        "overall_fit_summary": "Solid fit.",
    },
}
GAP_PAYLOAD = {
    "summary": "GAP summary.",
    "data": {
        "readiness_score": 7,
        "strengths": [],
        "must_have_gaps": [],
        "nice_to_have_gaps": [],
        "recommended_next_steps": [],
    },
}
SHIFT_PAYLOAD = {
    "summary": "SHIFT summary.",
    "data": {
        "role_evolution_summary": "Stable role family.",
        "task_shifts": [],
        "durable_skills": [],
        "adjacent_paths": [],
        "ai_fluency_guidance": [],
    },
}

DEFAULT_PAYLOADS = {"FIT": FIT_PAYLOAD, "GAP": GAP_PAYLOAD, "SHIFT": SHIFT_PAYLOAD}


class FakeClient:
    """Routes to a feature's payload by sniffing the feature name out of the
    prompt contract, mirroring build_demo_cache.py's own _MockClient."""

    def __init__(self, payloads=None):
        self.payloads = payloads or dict(DEFAULT_PAYLOADS)
        self.calls = []

    def complete(self, *, messages, role=None, **_):
        self.calls.append(messages)
        blob = " ".join(
            m.get("content", "") if isinstance(m, dict) else getattr(m, "content", "") for m in messages
        )
        # Match the literal `"feature": "GAP"` marker from feature_contract()'s
        # JSON dump, not a bare substring -- prompt bodies can otherwise
        # mention another feature's name in passing (e.g. FIT's prompt
        # discussing skill "gaps") and misroute a naive substring check.
        for feature, payload in self.payloads.items():
            if f'"feature": "{feature}"' in blob:
                return AIResponse(text=json.dumps(payload), raw={"choices": []}, model="fake-model")
        return AIResponse(text=json.dumps({"data": {}}), raw={"choices": []}, model="fake-model")


@pytest.fixture(autouse=True)
def _isolated_dirs(tmp_path, monkeypatch):
    students_dir = tmp_path / "data" / "students"
    output_dir = tmp_path / "frontend" / "public" / "data"
    students_dir.mkdir(parents=True)
    (students_dir / "student_testStudent.json").write_text(json.dumps(SAMPLE_PROFILE), encoding="utf-8")

    monkeypatch.setattr(bdc, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(bdc, "_STUDENTS_DIR", students_dir)
    monkeypatch.setattr(bdc, "_OUTPUT_DIR", output_dir)
    return {"students_dir": students_dir, "output_dir": output_dir}


def _out_path(dirs):
    return dirs["output_dir"] / "analysis_testStudent.json"


def test_feature_omitted_defaults_to_all_three(monkeypatch, _isolated_dirs):
    fake = FakeClient()
    monkeypatch.setattr(bdc, "_make_client", lambda mock: fake)

    exit_code = bdc.build(only=["testStudent"], mock=False, feature=None)

    assert exit_code == 0
    written = json.loads(_out_path(_isolated_dirs).read_text())
    assert set(written["results"]) == {"FIT", "GAP", "SHIFT"}
    assert written["features_requested"] == ["FIT", "GAP", "SHIFT"]
    assert written["status"] == "success"


def test_feature_flag_limits_which_features_are_requested(monkeypatch, _isolated_dirs):
    fake = FakeClient()
    monkeypatch.setattr(bdc, "_make_client", lambda mock: fake)

    bdc.build(only=["testStudent"], mock=False, feature=["GAP"])

    written = json.loads(_out_path(_isolated_dirs).read_text())
    assert set(written["results"]) == {"GAP"}
    # Only one client call this run (GapRunner) -- FIT/SHIFT runners never invoked.
    assert len(fake.calls) == 1


def test_full_write_when_no_prior_file_exists(monkeypatch, _isolated_dirs):
    assert not _out_path(_isolated_dirs).exists()
    fake = FakeClient()
    monkeypatch.setattr(bdc, "_make_client", lambda mock: fake)

    bdc.build(only=["testStudent"], mock=False, feature=None)

    written = json.loads(_out_path(_isolated_dirs).read_text())
    assert written["results"]["FIT"]["summary"] == "FIT summary."
    assert written["results"]["GAP"]["summary"] == "GAP summary."
    assert written["results"]["SHIFT"]["summary"] == "SHIFT summary."


def test_merge_preserves_untouched_features_and_updates_requested_ones(monkeypatch, _isolated_dirs):
    # First pass: full run, establishes a baseline cache file.
    first_client = FakeClient()
    monkeypatch.setattr(bdc, "_make_client", lambda mock: first_client)
    bdc.build(only=["testStudent"], mock=False, feature=None)

    original = json.loads(_out_path(_isolated_dirs).read_text())
    original_fit = original["results"]["FIT"]
    original_shift = original["results"]["SHIFT"]

    # Second pass: only GAP requested, with a distinguishable new payload.
    new_gap_payload = {
        "summary": "NEW GAP summary after retry.",
        "data": {
            "readiness_score": 9,
            "strengths": [],
            "must_have_gaps": [],
            "nice_to_have_gaps": [],
            "recommended_next_steps": [],
        },
    }
    second_client = FakeClient({"GAP": new_gap_payload})
    monkeypatch.setattr(bdc, "_make_client", lambda mock: second_client)
    bdc.build(only=["testStudent"], mock=False, feature=["GAP"])

    merged = json.loads(_out_path(_isolated_dirs).read_text())

    # Untouched features carried over byte-for-byte.
    assert merged["results"]["FIT"] == original_fit
    assert merged["results"]["SHIFT"] == original_shift
    # Requested feature updated to the fresh value.
    assert merged["results"]["GAP"]["summary"] == "NEW GAP summary after retry."
    assert merged["results"]["GAP"]["data"]["readiness_score"] == 9
    # Only the GAP call happened this run.
    assert len(second_client.calls) == 1
    # Top-level fields recomputed over the full merged set, not just the fresh subset.
    assert set(merged["results"]) == {"FIT", "GAP", "SHIFT"}
    assert merged["features_requested"] == ["FIT", "GAP", "SHIFT"]
    assert merged["status"] == "success"


def test_merge_recomputes_status_when_requested_feature_fails(monkeypatch, _isolated_dirs):
    first_client = FakeClient()
    monkeypatch.setattr(bdc, "_make_client", lambda mock: first_client)
    bdc.build(only=["testStudent"], mock=False, feature=None)

    class FailingClient:
        calls = []

        def complete(self, **kwargs):
            raise RuntimeError("simulated timeout")

    monkeypatch.setattr(bdc, "_make_client", lambda mock: FailingClient())
    bdc.build(only=["testStudent"], mock=False, feature=["GAP"])

    merged = json.loads(_out_path(_isolated_dirs).read_text())
    assert merged["results"]["GAP"]["status"] == "failed"
    assert merged["results"]["FIT"]["status"] == "success"
    assert merged["results"]["SHIFT"]["status"] == "success"
    # Mixed success/failure across the merged set -> partial_success, matching
    # orchestrator.summarize_status()'s existing rule for a single full run.
    assert merged["status"] == "partial_success"


# ---------------------------------------------------------------- mock routing
# _MockClient used to route on `if "GAP" in blob.upper()` against the whole
# concatenated blob, so every prompt containing the word "gap" -- SHIFT has said
# "The gap is articulation, not adoption" since v1.0 -- got the GAP payload.
# --mock silently only ever exercised one feature.

_RUNNERS = ["GAP", "FIT", "SHIFT", "PROFESSOR_COMMENTS"]


def _runner_for(feature):
    from GradusIQ_career.features.orchestrator import RUNNERS

    return RUNNERS[feature]


@pytest.mark.parametrize("feature", _RUNNERS)
def test_mock_client_routes_each_feature_to_its_own_payload(feature):
    runner = _runner_for(feature)(client=bdc._MockClient())
    contract_blob = json.dumps(runner.feature_contract(), indent=2)

    payload = bdc._MockClient._payload_for(contract_blob)

    assert payload is bdc._MockClient._PAYLOADS[feature]


@pytest.mark.parametrize("feature", _RUNNERS)
def test_mock_payload_matches_the_runners_output_contract(feature):
    """The guard that would have caught the stale payloads.

    Mock output that doesn't match the contract makes --mock a false green:
    the pipeline "passes" while producing something the frontend cannot read.
    """
    runner = _runner_for(feature)(client=bdc._MockClient())

    assert set(bdc._MockClient._PAYLOADS[feature]) == set(runner.output_contract)


def test_mock_payload_nested_items_match_contract_item_shape():
    # Contract list entries that are dicts describe a required item shape --
    # SHIFT's adjacent_paths/task_shifts/durable_skills all are, and the old
    # mock returned bare strings for them.
    for feature in _RUNNERS:
        runner = _runner_for(feature)(client=bdc._MockClient())
        payload = bdc._MockClient._PAYLOADS[feature]
        for key, spec in runner.output_contract.items():
            if not (isinstance(spec, list) and spec and isinstance(spec[0], dict)):
                continue
            for item in payload[key]:
                assert set(item) == set(spec[0]), f"{feature}.{key} item shape"


def test_unrecognized_prompt_still_degrades_to_a_note():
    assert "note" in bdc._MockClient._payload_for("nothing identifying here")
