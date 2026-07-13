import itertools
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
# 15-1252.00 (Software Developers) is not one of the 10 occupations in the
# small real-O*NET catalog, so a fresh agent result for it is expected to
# come back tagged "agent" (format-valid, uncorroborated), not
# "agent_onet_corroborated".
EXPECTED_VALID_RESULT = dict(VALID_PAYLOAD, soc_source="agent")

# 13-2051.00 (Financial and Investment Analysts) IS one of the 10 occupations
# in data/reference/onet_soc_requirements.json -- used to test the
# corroborated-source tag.
ONET_CORROBORATED_PAYLOAD = dict(VALID_PAYLOAD, soc_code="13-2051.00", soc_title="Financial and Investment Analysts")

# 17-2072.00 (Electronics Engineers) is well-formed, not in the static 14
# curated role_requirements.json entries, and not in the small O*NET
# catalog either -- this is the shape of the real-world case (e.g. the
# agent's actual "Embedded Systems Intern" answer) that the old allowlist
# guard used to silently discard.
NOVEL_SOC_PAYLOAD = dict(VALID_PAYLOAD, soc_code="17-2072.00", soc_title="Electronics Engineers, Except Computer")


def test_successful_lookup_with_mocked_tool_calls_returns_correct_schema():
    client = FakeClient([_tool_call_message(), _final_message(VALID_PAYLOAD)])

    result = agent.get_role_requirements("Software Engineering Intern", client=client)

    assert result == EXPECTED_VALID_RESULT
    assert len(client.calls) == 2
    # second call must include the tool result as a "tool" message
    tool_messages = [m for m in client.calls[1]["messages"] if m.get("role") == "tool"]
    assert len(tool_messages) == 1


def test_well_formed_soc_code_outside_the_static_allowlist_is_accepted():
    # Core regression test for the guard change: this used to return None
    # because "17-2072.00" isn't one of the 14 codes in
    # data/role_requirements.json. The agent did real, valid research beyond
    # that curated list, and that must no longer be discarded.
    client = FakeClient([_final_message(NOVEL_SOC_PAYLOAD)])

    result = agent.get_role_requirements("Embedded Systems Intern", client=client)

    assert result == dict(NOVEL_SOC_PAYLOAD, soc_source="agent")


def test_soc_code_present_in_onet_catalog_is_corroborated():
    client = FakeClient([_final_message(ONET_CORROBORATED_PAYLOAD)])

    result = agent.get_role_requirements("Finance Intern", client=client)

    assert result["soc_source"] == "agent_onet_corroborated"


def test_soc_code_absent_from_onet_catalog_is_uncorroborated():
    client = FakeClient([_final_message(VALID_PAYLOAD)])

    result = agent.get_role_requirements("Software Engineering Intern", client=client)

    assert result["soc_source"] == "agent"


def test_malformed_soc_code_format_returns_none():
    bad_payload = dict(VALID_PAYLOAD, soc_code="not-a-code")
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


class _FakeTime:
    """A scripted stand-in for the ``time`` module, bound only inside
    ``role_research_agent``'s own namespace (see the test below) -- unlike
    ``monkeypatch.setattr(agent.time, "monotonic", ...)``, this never touches
    the real, process-wide ``time`` module, so it can't be desynced by
    unrelated code (other tests' background threads, pytest internals, etc.)
    also calling ``time.monotonic()`` during the test.
    """

    def __init__(self, values):
        self._values = iter(values)

    def monotonic(self):
        return next(self._values)


def test_time_budget_exceeded_before_final_round_aborts_and_returns_none(monkeypatch):
    # Deadline set at 90.0; rounds 0-2 each check in under budget, then the
    # final round's own deadline check (before it would force an answer)
    # trips -- the forced-answer path must not bypass the time budget.
    fake_time = _FakeTime(itertools.chain([0.0, 1.0, 2.0, 3.0], itertools.repeat(91.0)))
    monkeypatch.setattr(agent, "time", fake_time)
    client = FakeClient(
        [
            _tool_call_message("call_0"),
            _tool_call_message("call_1"),
            _tool_call_message("call_2"),
        ]
    )

    result = agent.get_role_requirements("Software Engineering Intern", client=client)

    assert result is None
    assert len(client.calls) == 3  # rounds 0-2 ran; the final round never got called


def test_final_round_forces_answer_when_model_would_otherwise_keep_requesting_tools():
    # Rounds 0-2 exhaust the search budget as before. Previously, if the
    # model still returned tool_calls on round 3, the loop aborted with None
    # without ever letting the model answer. Now tools are withheld on the
    # final round, so a model that would otherwise ask for a 4th search is
    # forced to respond with content instead -- this is the core regression
    # case for the bug: a role that used to fail now succeeds.
    client = FakeClient(
        [
            _tool_call_message("call_0"),
            _tool_call_message("call_1"),
            _tool_call_message("call_2"),
            _final_message(VALID_PAYLOAD),
        ]
    )

    result = agent.get_role_requirements("Software Engineering Intern", client=client)

    assert result == EXPECTED_VALID_RESULT
    assert len(client.calls) == 4
    final_call_kwargs = client.calls[-1]
    # tools must be structurally withheld, not just hoped-away
    assert final_call_kwargs.get("extra_body") is None
    assert any(
        m.get("role") == "user" and "final JSON" in (m.get("content") or "")
        for m in final_call_kwargs["messages"]
    )


def test_final_round_forced_answer_failing_schema_validation_still_returns_none():
    bad_payload = dict(VALID_PAYLOAD, soc_code="not-a-code")
    client = FakeClient(
        [
            _tool_call_message("call_0"),
            _tool_call_message("call_1"),
            _tool_call_message("call_2"),
            _final_message(bad_payload),
        ]
    )

    result = agent.get_role_requirements("Software Engineering Intern", client=client)

    assert result is None


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


def test_missing_tavily_key_logs_a_distinct_warning_not_a_silent_fallback(monkeypatch, caplog):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    with caplog.at_level("WARNING", logger="CampusIQ_career.features.role_research_agent"):
        result = agent._tavily_client()

    assert result is None
    assert any("TAVILY_API_KEY not set" in record.message for record in caplog.records)


def test_cache_hit_on_second_call_skips_the_agent():
    client = FakeClient([_tool_call_message(), _final_message(VALID_PAYLOAD)])

    first = agent.get_role_requirements("Software Engineering Intern", client=client)
    assert first == EXPECTED_VALID_RESULT
    calls_after_first = len(client.calls)

    second = agent.get_role_requirements("Software Engineering Intern", client=client)

    assert second == EXPECTED_VALID_RESULT
    assert len(client.calls) == calls_after_first  # no new client calls on the cache hit


def test_cache_is_not_written_on_fallback_result():
    client = FakeClient([AIRequestError("network down")])

    result = agent.get_role_requirements("Software Engineering Intern", client=client)

    assert result is None
    assert not agent._CACHE_PATH.exists()


def test_cache_is_not_written_on_malformed_soc_code():
    bad_payload = dict(VALID_PAYLOAD, soc_code="not-a-code")
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

    assert result == EXPECTED_VALID_RESULT
    assert len(client.calls) == 2  # agent was actually invoked, cache miss was honored


def test_system_prompt_constrains_soc_code_to_entry_level_occupations():
    # Guards against a real, observed bias: without this, the model drifts
    # toward manager/supervisor-tier SOC codes for intern-level roles (e.g.
    # "Human Resources Managers" instead of "Human Resources Specialists"
    # for an HR internship). This must survive future prompt edits.
    prompt = agent._SYSTEM_PROMPT
    assert "entry-level" in prompt
    assert "Managers" in prompt and "Supervisors" in prompt and "Directors" in prompt


def test_role_research_model_resolves_to_deepseek_v4_flash_by_default(monkeypatch):
    monkeypatch.delenv("CAMPUSIQ_MODEL_ROLE_RESEARCH", raising=False)

    assert get_model_for_role("role_research") == OPENROUTER_DEEPSEEK_V4_FLASH


def test_role_research_model_env_override_wins(monkeypatch):
    monkeypatch.setenv("CAMPUSIQ_MODEL_ROLE_RESEARCH", "openrouter/test-role-research-model")

    assert get_model_for_role("role_research") == "openrouter/test-role-research-model"
