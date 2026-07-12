import json

import pytest

from CampusIQ_career.ai.errors import AIConfigError, AIRequestError, AIResponseParseError
from CampusIQ_career.ai.model_config import OPENROUTER_DEEPSEEK_V4_FLASH, get_model_for_role
from CampusIQ_career.features import role_research_agent as agent


@pytest.fixture(autouse=True)
def _isolated_cache_path(tmp_path, monkeypatch):
    # Every test gets its own cache file so lookups here never read/write the
    # real data/.cache/role_research_cache.json used by the running app.
    monkeypatch.setattr(agent, "_CACHE_PATH", tmp_path / "role_research_cache.json")


def _final_message(payload: dict) -> dict:
    return {"content": json.dumps(payload), "tool_calls": None}


def _tool_call_message(call_id: str = "call_1") -> dict:
    return {
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "function": {
                    "name": "web_search",
                    "arguments": json.dumps({"query": "software engineering intern skills"}),
                },
            }
        ],
    }


class FakeClient:
    """Mirrors tests/test_career_features.py's FakeClient mock-injection style.

    Simulates OpenRouterClient.complete_message(), which returns the raw
    assistant message dict directly (not wrapped in AIResponse/.raw).
    """

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def complete_message(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("FakeClient ran out of scripted responses")
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


VALID_PAYLOAD = {
    "soc_code": "15-1252.00",
    "soc_title": "Software Developers",
    "must_have_skills": ["Python", "Git"],
    "nice_to_have_skills": ["Docker"],
    "must_have_certifications": [],
    "nice_to_have_certifications": ["AWS Certified Cloud Practitioner"],
}


def test_successful_lookup_with_mocked_tool_calls_returns_correct_schema():
    client = FakeClient([_tool_call_message(), _final_message(VALID_PAYLOAD)])

    result = agent.get_role_requirements("Software Engineering Intern", client=client)

    assert result == VALID_PAYLOAD
    assert len(client.calls) == 2
    # second call must include the tool result as a "tool" message
    tool_messages = [m for m in client.calls[1]["messages"] if m.get("role") == "tool"]
    assert len(tool_messages) == 1


def test_hallucinated_soc_code_returns_none():
    bad_payload = dict(VALID_PAYLOAD, soc_code="99-9999.99")
    client = FakeClient([_final_message(bad_payload)])

    result = agent.get_role_requirements("Software Engineering Intern", client=client)

    assert result is None


def test_tool_loop_exceeding_max_rounds_aborts_and_returns_none():
    # Client always wants to call a tool -- never returns a final answer.
    client = FakeClient([_tool_call_message(f"call_{i}") for i in range(10)])

    result = agent.get_role_requirements("Software Engineering Intern", client=client)

    assert result is None
    # 3 tool rounds executed + 1 final round that still requested a tool call = 4 calls.
    assert len(client.calls) == 4


def test_tool_loop_exceeding_time_budget_aborts_and_returns_none(monkeypatch):
    # First monotonic() call sets the deadline; second call (top of loop,
    # before the first client call) is already past it.
    clock = iter([0.0, 91.0])
    monkeypatch.setattr(agent.time, "monotonic", lambda: next(clock))
    client = FakeClient([_tool_call_message()])

    result = agent.get_role_requirements("Software Engineering Intern", client=client)

    assert result is None
    assert len(client.calls) == 0


def test_malformed_json_in_final_response_returns_none():
    client = FakeClient([{"content": "not json", "tool_calls": None}])

    result = agent.get_role_requirements("Software Engineering Intern", client=client)

    assert result is None


@pytest.mark.parametrize(
    "exc",
    [
        AIConfigError("missing key"),
        AIRequestError("network down"),
        AIResponseParseError("bad body"),
        ValueError("boom"),
    ],
)
def test_caught_exceptions_return_none_without_raising(exc):
    client = FakeClient([exc])

    result = agent.get_role_requirements("Software Engineering Intern", client=client)

    assert result is None


def test_timeout_error_returns_none_without_raising():
    class TimeoutClient:
        def complete_message(self, **kwargs):
            raise TimeoutError("lookup timed out")

    result = agent.get_role_requirements("Software Engineering Intern", client=TimeoutClient())

    assert result is None


def test_blank_role_returns_none_without_calling_client():
    client = FakeClient([])

    result = agent.get_role_requirements("   ", client=client)

    assert result is None
    assert client.calls == []


def test_cache_hit_on_second_call_skips_the_agent():
    client = FakeClient([_tool_call_message(), _final_message(VALID_PAYLOAD)])

    first = agent.get_role_requirements("Software Engineering Intern", client=client)
    assert first == VALID_PAYLOAD
    calls_after_first = len(client.calls)

    second = agent.get_role_requirements("Software Engineering Intern", client=client)

    assert second == VALID_PAYLOAD
    assert len(client.calls) == calls_after_first  # no new client calls on the cache hit


def test_cache_is_not_written_on_fallback_result():
    client = FakeClient([AIRequestError("network down")])

    result = agent.get_role_requirements("Software Engineering Intern", client=client)

    assert result is None
    assert not agent._CACHE_PATH.exists()


def test_cache_is_not_written_on_hallucinated_soc_code():
    bad_payload = dict(VALID_PAYLOAD, soc_code="99-9999.99")
    client = FakeClient([_final_message(bad_payload)])

    result = agent.get_role_requirements("Software Engineering Intern", client=client)

    assert result is None
    assert not agent._CACHE_PATH.exists()


def test_stale_or_malformed_cache_entry_is_treated_as_a_miss(tmp_path):
    agent._CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    agent._CACHE_PATH.write_text(
        json.dumps({"Software Engineering Intern": {"soc_code": "15-1252.00"}}),  # missing required keys
        encoding="utf-8",
    )
    client = FakeClient([_tool_call_message(), _final_message(VALID_PAYLOAD)])

    result = agent.get_role_requirements("Software Engineering Intern", client=client)

    assert result == VALID_PAYLOAD
    assert len(client.calls) == 2  # agent was actually invoked, cache miss was honored


def test_role_research_model_resolves_to_deepseek_v4_flash_by_default(monkeypatch):
    monkeypatch.delenv("CAMPUSIQ_MODEL_ROLE_RESEARCH", raising=False)

    assert get_model_for_role("role_research") == OPENROUTER_DEEPSEEK_V4_FLASH


def test_role_research_model_env_override_wins(monkeypatch):
    monkeypatch.setenv("CAMPUSIQ_MODEL_ROLE_RESEARCH", "openrouter/test-role-research-model")

    assert get_model_for_role("role_research") == "openrouter/test-role-research-model"
