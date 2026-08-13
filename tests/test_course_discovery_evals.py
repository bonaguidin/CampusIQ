import json

import pytest

from GradusIQ_career.course_discovery.evals import C2_SCENARIOS


def test_c2_scenarios_are_focused_unique_synthetic_and_offline(monkeypatch):
    monkeypatch.setattr("socket.create_connection", lambda *a, **k: pytest.fail("network forbidden"))
    assert 8 <= len(C2_SCENARIOS) <= 9
    assert len({item.scenario_id for item in C2_SCENARIOS}) == len(C2_SCENARIOS)
    rendered = json.dumps([item.model_dump(mode="json") for item in C2_SCENARIOS])
    assert "student_id" not in rendered and "@" not in rendered
    assert all(item.live_eligible is False for item in C2_SCENARIOS)
    assert {item.expected_state for item in C2_SCENARIOS} == {
        "verified", "excluded", "unresolved", "rejected", "empty"
    }
