import pytest

from GradusIQ_career.features import gap as gap_module


@pytest.fixture(autouse=True)
def _no_live_role_research_by_default(request, monkeypatch):
    """Default role_research_agent.get_role_requirements() to a static-only miss.

    GradusIQ_career/api.py calls load_dotenv() on import, and .env carries
    real OPENROUTER_API_KEY / TAVILY_API_KEY for local development. Once any
    test imports api (directly or via the TestClient fixture in
    tests/test_api.py), those credentials are live in this process for the
    rest of the suite. GapRunner.role_requirements_for() calls the live
    research agent first for every target role -- without this default,
    every GAP test elsewhere in the suite that doesn't itself mock the agent
    would send real network requests (OpenRouter + Tavily) and could block
    for up to the agent's 90s research budget per role.

    Exempts tests/test_role_research_agent.py, which tests the real
    role_research_agent module directly and must not have it stubbed out.

    Tests that want to exercise the agent path from gap.py's side (see
    tests/test_career_features.py) call monkeypatch.setattr(...) again
    within the test body, which overrides this default for that test only.
    """
    if request.module.__name__.endswith("test_role_research_agent"):
        return
    monkeypatch.setattr(
        gap_module.role_research_agent,
        "get_role_requirements",
        lambda role, client=None: None,
    )
    # Same reasoning for SHIFT's trend research: ShiftRunner calls
    # get_role_trends once per target role, and it has no static fallback to
    # short-circuit the call. Patched on the same module object gap.py holds,
    # which is the one shift.py imports too.
    monkeypatch.setattr(
        gap_module.role_research_agent,
        "get_role_trends",
        lambda role, client=None: None,
    )
