import itertools
import json
from pathlib import Path

import pytest

from CampusIQ_career.ai.errors import AIConfigError, AIRequestError, AIResponseParseError
from CampusIQ_career.ai.model_config import OPENROUTER_DEEPSEEK_V4_FLASH, get_model_for_role
from CampusIQ_career.ai.openrouter_client import OpenRouterClient
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


class FakeHTTPResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class SequencedHTTPSession:
    def __init__(self, messages):
        self.messages = list(messages)
        self.calls = []

    def post(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        message = self.messages.pop(0)
        return FakeHTTPResponse({"choices": [{"message": message}]})


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


def test_real_openrouter_serializer_preserves_tool_relationship_in_second_request(monkeypatch):
    session = SequencedHTTPSession([_tool_call_message("call_123"), _final_message(VALID_PAYLOAD)])
    client = OpenRouterClient(api_key="test-key", session=session)
    monkeypatch.setattr(agent, "_run_web_search", lambda arguments: '{"results":[]}')

    result = agent.get_role_requirements("Software Engineering Intern", client=client)

    assert result == EXPECTED_VALID_RESULT
    assert len(session.calls) == 2
    second_messages = session.calls[1]["kwargs"]["json"]["messages"]
    assert second_messages[:2] == [
        {"role": "system", "content": agent._SYSTEM_PROMPT},
        {"role": "user", "content": "Target role: Software Engineering Intern"},
    ]
    assistant = second_messages[2]
    tool = second_messages[3]
    assert assistant["tool_calls"][0]["id"] == "call_123"
    assert tool["tool_call_id"] == "call_123"
    assert tool["tool_call_id"] == assistant["tool_calls"][0]["id"]
    assert tool["content"] == '{"results":[]}'


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


# ═══════════════════════════════════════════════════════════════════════════
# Free-text bounds: _MAX_FIELD_CHARS per string, _MAX_LIST_ITEMS per list.
#
# Every field below reaches the GAP prompt verbatim (gap.py
# _merge_requirements -> build_student_context -> base.py json.dumps), so
# unbounded model output synthesized from third-party search results is the
# injection surface these caps close. Reject, never truncate.
# ═══════════════════════════════════════════════════════════════════════════


def _payload_with(**overrides):
    return dict(VALID_PAYLOAD, **overrides)


# 1. Exactly at the cap passes -- boundary is inclusive.
@pytest.mark.parametrize("field", agent._LIST_KEYS)
def test_list_element_at_exactly_the_char_cap_passes(field):
    at_cap = "x" * agent._MAX_FIELD_CHARS
    client = FakeClient([_final_message(_payload_with(**{field: [at_cap]}))])

    result = agent.get_role_requirements("Software Engineering Intern", client=client)

    assert result is not None
    assert result[field] == [at_cap]
    assert len(result[field][0]) == 120


def test_soc_title_at_exactly_the_char_cap_passes():
    at_cap = "T" * agent._MAX_FIELD_CHARS
    client = FakeClient([_final_message(_payload_with(soc_title=at_cap))])

    result = agent.get_role_requirements("Software Engineering Intern", client=client)

    assert result is not None
    assert result["soc_title"] == at_cap


# 2. One character over the cap fails the entry.
@pytest.mark.parametrize("field", agent._LIST_KEYS)
def test_list_element_one_over_the_char_cap_fails(field):
    over_cap = "x" * (agent._MAX_FIELD_CHARS + 1)
    client = FakeClient([_final_message(_payload_with(**{field: [over_cap]}))])

    result = agent.get_role_requirements("Software Engineering Intern", client=client)

    assert result is None
    # Rejected content must not be persisted.
    assert not agent._CACHE_PATH.exists()


def test_soc_title_one_over_the_char_cap_fails():
    client = FakeClient(
        [_final_message(_payload_with(soc_title="T" * (agent._MAX_FIELD_CHARS + 1)))]
    )

    result = agent.get_role_requirements("Software Engineering Intern", client=client)

    assert result is None
    assert not agent._CACHE_PATH.exists()


# 3. One oversized element rejects the WHOLE entry, not just that element.
def test_one_oversized_element_rejects_the_entire_entry():
    payload = _payload_with(
        must_have_skills=[
            "Python",
            "x" * (agent._MAX_FIELD_CHARS + 1),  # the single offender
            "Git",
        ],
        nice_to_have_skills=["Docker"],
    )
    client = FakeClient([_final_message(payload)])

    result = agent.get_role_requirements("Software Engineering Intern", client=client)

    # Not a filtered list -- nothing at all comes back.
    assert result is None
    assert not agent._CACHE_PATH.exists()


# 4. A realistic response with ordinary skill/cert names passes unchanged.
def test_realistic_role_research_response_passes_unchanged():
    realistic = {
        "soc_code": "13-2051.00",
        "soc_title": "Financial and Investment Analysts",
        "must_have_skills": [
            "Financial modeling",
            "Excel",
            "Data analysis",
            "Written communication",
            "Attention to detail",
        ],
        "nice_to_have_skills": ["SQL", "Python", "Tableau", "Bloomberg Terminal"],
        "must_have_certifications": [],
        "nice_to_have_certifications": [
            "Bloomberg Market Concepts (BMC)",
            "CFA Level I candidate status",
        ],
    }
    client = FakeClient([_final_message(realistic)])

    result = agent.get_role_requirements("Finance Intern", client=client)

    assert result == dict(realistic, soc_source="agent_onet_corroborated")
    # Every field survived byte-for-byte -- no truncation, no reordering.
    for key in agent._LIST_KEYS:
        assert result[key] == realistic[key]


def test_every_entry_in_the_real_cache_file_still_validates():
    """The shipped cache must not be invalidated by the new bounds.

    Guards against picking caps so tight that legitimate existing research is
    evicted and silently re-fetched on the next GAP run.
    """
    real_cache = (
        Path(__file__).resolve().parents[1] / "data" / ".cache" / "role_research_cache.json"
    )
    if not real_cache.exists():
        pytest.skip("no real cache file checked in")

    entries = json.loads(real_cache.read_text(encoding="utf-8"))
    assert entries, "cache file is empty; this test would be vacuous"
    for role, entry in entries.items():
        assert agent._validate_schema(entry) is not None, f"{role} no longer validates"


# 5. A pre-existing on-disk entry that violates the new bounds is a cache
#    MISS on read, not an exception -- matching the module's fail-safe pattern.
def test_preexisting_oversized_cache_entry_is_treated_as_a_miss():
    # Written directly to the cache path, bypassing validation entirely --
    # exactly how an entry created before these bounds existed would look.
    agent._CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    agent._CACHE_PATH.write_text(
        json.dumps(
            {
                "Software Engineering Intern": dict(
                    VALID_PAYLOAD,
                    soc_source="agent",
                    must_have_skills=["y" * 500],  # far over the cap
                )
            }
        ),
        encoding="utf-8",
    )

    # No exception: the stale entry is ignored and the agent runs instead.
    client = FakeClient([_tool_call_message(), _final_message(VALID_PAYLOAD)])
    result = agent.get_role_requirements("Software Engineering Intern", client=client)

    assert result == EXPECTED_VALID_RESULT
    assert len(client.calls) == 2  # cache miss honored, agent actually invoked


def test_preexisting_overlong_list_cache_entry_is_treated_as_a_miss():
    agent._CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    agent._CACHE_PATH.write_text(
        json.dumps(
            {
                "Software Engineering Intern": dict(
                    VALID_PAYLOAD,
                    soc_source="agent",
                    nice_to_have_skills=[f"skill-{i}" for i in range(agent._MAX_LIST_ITEMS + 1)],
                )
            }
        ),
        encoding="utf-8",
    )

    client = FakeClient([_tool_call_message(), _final_message(VALID_PAYLOAD)])
    result = agent.get_role_requirements("Software Engineering Intern", client=client)

    assert result == EXPECTED_VALID_RESULT
    assert len(client.calls) == 2


# 6. Already-constrained fields are unaffected by the new length bound.
def test_soc_code_is_unaffected_by_the_char_cap():
    # A valid SOC code is 10 chars -- nowhere near the cap, and its own regex
    # is what constrains it. Still accepted exactly as before.
    client = FakeClient([_final_message(_payload_with(soc_code="17-2072.00"))])

    result = agent.get_role_requirements("Embedded Systems Intern", client=client)

    assert result is not None
    assert result["soc_code"] == "17-2072.00"
    assert len(result["soc_code"]) < agent._MAX_FIELD_CHARS


def test_malformed_soc_code_still_rejected_for_format_not_length():
    # Short enough to clear any length bound, still rejected on format --
    # proves the regex gate is untouched by the new checks.
    client = FakeClient([_final_message(_payload_with(soc_code="not-a-code"))])

    result = agent.get_role_requirements("Software Engineering Intern", client=client)

    assert result is None


def test_empty_lists_remain_valid():
    # The cap is an upper bound only; empty is still legitimate (every real
    # cache entry has must_have_certifications == []).
    payload = _payload_with(
        must_have_skills=[],
        nice_to_have_skills=[],
        must_have_certifications=[],
        nice_to_have_certifications=[],
    )
    client = FakeClient([_final_message(payload)])

    result = agent.get_role_requirements("Software Engineering Intern", client=client)

    assert result is not None
    assert result["must_have_skills"] == []


# 7. Exactly at the list cap passes.
@pytest.mark.parametrize("field", agent._LIST_KEYS)
def test_list_with_exactly_the_item_cap_passes(field):
    at_cap = [f"skill-{i}" for i in range(agent._MAX_LIST_ITEMS)]
    client = FakeClient([_final_message(_payload_with(**{field: at_cap}))])

    result = agent.get_role_requirements("Software Engineering Intern", client=client)

    assert result is not None
    assert len(result[field]) == 20


# 8. One element over the list cap fails.
@pytest.mark.parametrize("field", agent._LIST_KEYS)
def test_list_one_over_the_item_cap_fails(field):
    over_cap = [f"skill-{i}" for i in range(agent._MAX_LIST_ITEMS + 1)]
    client = FakeClient([_final_message(_payload_with(**{field: over_cap}))])

    result = agent.get_role_requirements("Software Engineering Intern", client=client)

    assert result is None
    assert not agent._CACHE_PATH.exists()


def test_many_short_items_cannot_bypass_the_char_cap():
    # The volume expression of the same injection surface: each item is well
    # under the char cap, but the list as a whole is not.
    payload = _payload_with(must_have_skills=["ok"] * 200)
    client = FakeClient([_final_message(payload)])

    assert agent.get_role_requirements("Software Engineering Intern", client=client) is None


# ═══════════════════════════════════════════════════════════════════════════
# soc_source is a machine-set provenance tag, not free text: it must be one
# of the two values _run_tool_loop assigns, or absent entirely.
# ═══════════════════════════════════════════════════════════════════════════


# A valid soc_source in the set passes on re-validation (the _read_cache path).
@pytest.mark.parametrize("valid_source", sorted(agent._VALID_SOC_SOURCES))
def test_valid_soc_source_passes_on_cache_read(valid_source):
    agent._CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    agent._CACHE_PATH.write_text(
        json.dumps(
            {"Software Engineering Intern": dict(VALID_PAYLOAD, soc_source=valid_source)}
        ),
        encoding="utf-8",
    )

    # Ran out of scripted responses would raise -- a cache HIT is required here.
    client = FakeClient([])
    result = agent.get_role_requirements("Software Engineering Intern", client=client)

    assert result == dict(VALID_PAYLOAD, soc_source=valid_source)
    assert client.calls == []  # served from cache, agent never invoked


def test_valid_soc_source_set_matches_what_the_write_path_assigns():
    assert agent._VALID_SOC_SOURCES == {"agent", "agent_onet_corroborated"}
    # Both tags are actually reachable from a real lookup: EXPECTED_VALID_RESULT
    # carries "agent", and the corroborated payload carries the other.
    assert EXPECTED_VALID_RESULT["soc_source"] in agent._VALID_SOC_SOURCES


# An arbitrary soc_source fails and is treated as a miss on read.
@pytest.mark.parametrize(
    "bad_source",
    ["admin", "", "AGENT", "agent ", "static", "agent_onet", None, 1, ["agent"], {"a": 1}],
)
def test_arbitrary_soc_source_is_treated_as_a_cache_miss(bad_source):
    agent._CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    agent._CACHE_PATH.write_text(
        json.dumps({"Software Engineering Intern": dict(VALID_PAYLOAD, soc_source=bad_source)}),
        encoding="utf-8",
    )

    # No exception -- including for the unhashable list/dict cases, which would
    # raise TypeError from a bare `in <set>` check.
    client = FakeClient([_tool_call_message(), _final_message(VALID_PAYLOAD)])
    result = agent.get_role_requirements("Software Engineering Intern", client=client)

    assert result == EXPECTED_VALID_RESULT
    assert len(client.calls) == 2  # miss honored, agent actually re-ran


def test_model_supplied_bogus_soc_source_rejects_the_entry_on_write():
    # The model does not normally emit soc_source at all, but if it does, a
    # bogus value now fails validation rather than being silently overwritten.
    client = FakeClient([_final_message(dict(VALID_PAYLOAD, soc_source="admin"))])

    result = agent.get_role_requirements("Software Engineering Intern", client=client)

    assert result is None
    assert not agent._CACHE_PATH.exists()


def test_absent_soc_source_remains_valid_so_the_write_path_still_works():
    # Freshly parsed agent JSON carries no soc_source; _validate_schema must
    # accept that and let _run_tool_loop assign the tag afterwards.
    assert "soc_source" not in VALID_PAYLOAD
    assert agent._validate_schema(VALID_PAYLOAD) is not None

    client = FakeClient([_final_message(VALID_PAYLOAD)])
    result = agent.get_role_requirements("Software Engineering Intern", client=client)

    assert result == EXPECTED_VALID_RESULT
    assert result["soc_source"] == "agent"
