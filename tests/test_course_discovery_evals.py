import json

import pytest

from GradusIQ_career.evals.course_discovery_scenarios import COURSE_DISCOVERY_SCENARIOS


def test_c2_scenarios_are_focused_unique_synthetic_and_offline(monkeypatch):
    monkeypatch.setattr("socket.create_connection", lambda *a, **k: pytest.fail("network forbidden"))
    assert len(COURSE_DISCOVERY_SCENARIOS) == 6
    assert len({item.scenario_id for item in COURSE_DISCOVERY_SCENARIOS}) == 6
    rendered = json.dumps([item.model_dump(mode="json") for item in COURSE_DISCOVERY_SCENARIOS])
    assert "student_id" not in rendered and "@" not in rendered
    assert all(item.live_eligible is True for item in COURSE_DISCOVERY_SCENARIOS)
    assert all(item.features == {"course_discovery"} for item in COURSE_DISCOVERY_SCENARIOS)
