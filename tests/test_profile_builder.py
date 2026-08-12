"""Tests for GradusIQ_career.profile_builder.

The builder reconstructs a runner-compatible profile dict from Postgres rows.
Its contract is that the output is structurally interchangeable with what
api.load_student_profile returns from data/students/*.json.
"""

import json
from pathlib import Path

import pytest

from GradusIQ_career import api
from GradusIQ_career.profile_builder import (
    UNCONFIRMED_REASON,
    build_profile_from_supabase,
    ProfileBuildResult,
)


CONFIRMED = "2026-08-01T00:00:00Z"
REPO_ROOT = Path(__file__).resolve().parents[1]


class FakeSupabase:
    """Mimics the .table(...).select(...).eq(...).execute() chain."""

    def __init__(self, tables):
        self._tables = tables
        self._rows = []
        self.queried = []

    def table(self, name):
        self.queried.append(name)
        self._rows = list(self._tables.get(name, []))
        return self

    def select(self, *args, **kwargs):
        return self

    def eq(self, key, value):
        self._rows = [r for r in self._rows if r.get(key) == value]
        return self

    def execute(self):
        class _Resp:
            data = self._rows

        return _Resp()


def _student_row(sid="uuid-student-1"):
    return {
        "id": sid,
        "auth_user_id": "uuid-auth-1",
        "name": "Jordan Reyes",
        "classification": "Freshman",
        "major_current": "Business Administration",
        "major_intended": "Finance",
        "expected_graduation": "2029-05",
        "onboarding_stage": 3,
        "created_at": CONFIRMED,
        "updated_at": CONFIRMED,
    }


def _career_row(sid="uuid-student-1", confirmed=CONFIRMED):
    return {
        "id": "uuid-career-1",
        "student_id": sid,
        "target_roles": ["Business Analyst Intern", "Operations Intern"],
        "interests": ["operations", "finance", "analytics"],
        "career_goals": "Explore business internships.",
        "geographic_preference": "DFW metro preferred",
        "ai_anxiety_level": "moderate",
        "skills_technical": ["Excel", "PowerPoint"],
        "skills_soft": ["communication", "team collaboration"],
        "ai_exposure": "informal AI study support",
        "created_at": CONFIRMED,
        "updated_at": CONFIRMED,
        "source": "manual",
        "confirmed_at": confirmed,
    }


def _child(table, sid="uuid-student-1", confirmed=CONFIRMED, **fields):
    base = {
        "id": f"uuid-{table}-1",
        "career_profile_id": "uuid-career-1",
        "student_id": sid,
        "created_at": CONFIRMED,
        "updated_at": CONFIRMED,
        "source": "manual",
        "confirmed_at": confirmed,
    }
    base.update(fields)
    return base


INSTITUTION_ID = "uuid-inst-1"
INSTITUTION_NAME = "Texas A&M University"


def _tables(
    career_confirmed=CONFIRMED,
    include_career=True,
    children=None,
    include_home=True,
    include_institution=True,
):
    t = {"students": [_student_row()]}
    t["student_institutions"] = (
        [
            {
                "student_id": "uuid-student-1",
                "institution_id": INSTITUTION_ID,
                "relationship": "home",
            }
        ]
        if include_home
        else []
    )
    t["institutions"] = (
        [{"id": INSTITUTION_ID, "name": INSTITUTION_NAME}] if include_institution else []
    )
    t["career_profiles"] = [_career_row(confirmed=career_confirmed)] if include_career else []
    defaults = {
        "certifications": [
            _child("certifications", name="Excel Associate", issuer="Microsoft",
                   status="completed", date="2026-03")
        ],
        "work_experience": [
            _child("work_experience", employer="Mays Business School",
                   role="Case Team Member", duration="Spring 2026", location="College Station",
                   description="Prepared analyses.", skills_gained=["teamwork"])
        ],
        "projects": [
            _child("projects", name="Market Brief", timeframe="Spring 2026",
                   description="Customer analysis.", tools=["Excel"])
        ],
    }
    t.update(children if children is not None else defaults)
    return t


# 1. Shape matches a real demo JSON's career block, field-for-field.
def test_career_block_shape_matches_demo_json():
    demo = json.loads(
        (REPO_ROOT / "data" / "students" / "student_jordanReyes.json").read_text(encoding="utf-8")
    )
    expected_keys = set(demo["career"].keys())

    result = build_profile_from_supabase(FakeSupabase(_tables()), "uuid-student-1")

    assert isinstance(result, ProfileBuildResult)
    assert set(result.profile["career"].keys()) == expected_keys

    # skills_self_reported re-nests from three flat columns.
    skills = result.profile["career"]["skills_self_reported"]
    assert set(skills.keys()) == set(demo["career"]["skills_self_reported"].keys())
    assert skills == {
        "technical": ["Excel", "PowerPoint"],
        "soft": ["communication", "team collaboration"],
        "ai_exposure": "informal AI study support",
    }


def test_db_only_fields_are_projected_out_of_child_rows():
    demo = json.loads(
        (REPO_ROOT / "data" / "students" / "student_jordanReyes.json").read_text(encoding="utf-8")
    )
    result = build_profile_from_supabase(FakeSupabase(_tables()), "uuid-student-1")
    career = result.profile["career"]

    for table in ("certifications", "work_experience", "projects"):
        for item in career[table]:
            for banned in ("id", "career_profile_id", "student_id", "created_at",
                           "updated_at", "source", "confirmed_at"):
                assert banned not in item, f"{table} item leaked {banned}"
        # Key set matches the demo JSON's item shape exactly.
        if demo["career"][table]:
            assert set(career[table][0].keys()) == set(demo["career"][table][0].keys())


def test_student_id_is_the_uuid_as_a_string():
    result = build_profile_from_supabase(FakeSupabase(_tables()), "uuid-student-1")

    assert result.profile["student"]["id"] == "uuid-student-1"
    assert isinstance(result.profile["student"]["id"], str)
    # auth_user_id must never reach a payload that ends up in an LLM prompt.
    assert "auth_user_id" not in result.profile["student"]


# 2. An unconfirmed child row is excluded, recorded, and absent from the profile.
@pytest.mark.parametrize("table", ["certifications", "work_experience", "projects"])
def test_unconfirmed_child_row_is_excluded_and_recorded(table):
    children = {
        "certifications": [_child("certifications", name="Confirmed Cert", status="completed")],
        "work_experience": [_child("work_experience", employer="Confirmed Co", role="Intern")],
        "projects": [_child("projects", name="Confirmed Project")],
    }
    marker = f"UNCONFIRMED-{table}"
    name_field = {"certifications": "name", "work_experience": "employer", "projects": "name"}[table]
    children[table] = children[table] + [
        _child(table, confirmed=None, **{name_field: marker})
    ]

    result = build_profile_from_supabase(
        FakeSupabase(_tables(children=children)), "uuid-student-1"
    )

    # Not in the profile.
    serialized = json.dumps(result.profile)
    assert marker not in serialized
    assert len(result.profile["career"][table]) == 1

    # Recorded as an exclusion with the shared reason string.
    reasons = [reason for _row, reason in result.exclusions]
    assert UNCONFIRMED_REASON in reasons
    assert reasons.count(UNCONFIRMED_REASON) == 1
    excluded_row = [row for row, _ in result.exclusions][0]
    assert excluded_row[name_field] == marker


def test_unconfirmed_reason_matches_gpa_vocabulary():
    from GradusIQ_career.academics import gpa as gpa_module
    import inspect

    # gpa.py uses the literal "unconfirmed"; one vocabulary across both.
    assert UNCONFIRMED_REASON == "unconfirmed"
    assert '"unconfirmed"' in inspect.getsource(gpa_module.compute_gpa)


# 3. An unconfirmed career_profiles row drops the ENTIRE career block.
def test_unconfirmed_career_profile_drops_whole_career_block():
    result = build_profile_from_supabase(
        FakeSupabase(_tables(career_confirmed=None)), "uuid-student-1"
    )

    assert result.profile["career"] is None
    # Not partially populated -- no scalars survive either.
    assert "target_roles" not in json.dumps(result.profile)
    assert [r for _row, r in result.exclusions] == [UNCONFIRMED_REASON]
    # The student block is still returned; only career is withheld.
    assert result.profile["student"]["name"] == "Jordan Reyes"


# 4. No career_profiles row at all -> career is None (distinct from unconfirmed).
def test_no_career_profile_row_returns_career_none():
    result = build_profile_from_supabase(
        FakeSupabase(_tables(include_career=False)), "uuid-student-1"
    )

    assert result.profile["career"] is None
    # Distinct from the unconfirmed case: nothing was excluded, there was
    # simply nothing there.
    assert result.exclusions == []


def test_missing_students_row_raises_lookuperror():
    with pytest.raises(LookupError, match="No students row visible"):
        build_profile_from_supabase(FakeSupabase({"students": []}), "uuid-nobody")


# 6. A UUID student_id is a clean cache miss, never an exception.
def test_uuid_student_id_is_a_clean_cache_miss(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "CACHED_ANALYSIS_DIR", tmp_path)
    uuid_id = "8f14e45f-ceea-467a-9f0e-1c2d3e4f5a6b"

    # No cache file for a real student's slug at all.
    assert api.load_cached_feature_result("realStudent", "GAP", uuid_id) is None

    # Even against a demo cache file keyed on a small integer, the str()
    # comparison mismatches rather than raising.
    (tmp_path / "analysis_jordanReyes.json").write_text(
        json.dumps({"student_id": 601, "results": {}}), encoding="utf-8"
    )
    assert api.load_cached_feature_result("jordanReyes", "GAP", uuid_id) is None


# 7. GAP with an all-unconfirmed work_experience behaves exactly like an
#    absent list: status="skipped", standard missing-field error.
def test_gap_with_all_unconfirmed_work_experience_is_skipped():
    from GradusIQ_career.features.orchestrator import run_feature

    children = {
        "certifications": [_child("certifications", name="Cert", status="completed")],
        "work_experience": [
            _child("work_experience", confirmed=None, employer="Unreviewed Co", role="Intern")
        ],
        "projects": [_child("projects", name="Project")],
    }
    result = build_profile_from_supabase(
        FakeSupabase(_tables(children=children)), "uuid-student-1"
    )
    profile = result.profile

    assert profile["career"]["work_experience"] == []

    class _NoCallClient:
        def complete(self, **kwargs):
            raise AssertionError("AI client must not be called for a skipped feature")

    outcome = run_feature("GAP", profile, _NoCallClient())

    assert outcome["status"] == "skipped"
    assert outcome["summary"] == "Missing required fields for this feature."
    # The dotted path is asserted on missing_fields, which is where it now
    # lives; `errors` carries the student-facing label instead.
    assert any(item["path"] == "career.work_experience" for item in outcome["missing_fields"])
    assert any("Work experience" in e for e in outcome["errors"])


# ═══════════════════════════════════════════════════════════════════════════
# Home-institution join.
#
# Same two-hop query the GPA route performs, but degrading to null instead of
# raising 409: this constructor produces the best available profile, it does
# not enforce reference-data integrity that other layers already guard.
# ═══════════════════════════════════════════════════════════════════════════


# 1. Home institution present -> its name string.
def test_home_institution_name_is_resolved():
    result = build_profile_from_supabase(FakeSupabase(_tables()), "uuid-student-1")

    assert result.profile["student"]["institution"] == INSTITUTION_NAME
    assert isinstance(result.profile["student"]["institution"], str)


def test_only_the_home_relationship_is_used():
    tables = _tables()
    # A transfer institution must not win over (or stand in for) the home one.
    tables["student_institutions"] = [
        {
            "student_id": "uuid-student-1",
            "institution_id": "uuid-inst-transfer",
            "relationship": "transfer",
        }
    ] + tables["student_institutions"]
    tables["institutions"] = [
        {"id": "uuid-inst-transfer", "name": "Some Community College"},
        {"id": INSTITUTION_ID, "name": INSTITUTION_NAME},
    ]

    result = build_profile_from_supabase(FakeSupabase(tables), "uuid-student-1")

    assert result.profile["student"]["institution"] == INSTITUTION_NAME


# 2. No student_institutions row at all -> null, no exception.
def test_no_home_institution_row_yields_null_institution():
    result = build_profile_from_supabase(
        FakeSupabase(_tables(include_home=False)), "uuid-student-1"
    )

    assert result.profile["student"]["institution"] is None
    # The rest of the profile is unaffected -- this is a degraded field, not a
    # failed build.
    assert result.profile["student"]["name"] == "Jordan Reyes"
    assert result.profile["career"] is not None


# 3. Dangling reference (FK should prevent it) -> null, no IndexError.
def test_unresolvable_institution_row_yields_null_institution():
    result = build_profile_from_supabase(
        FakeSupabase(_tables(include_institution=False)), "uuid-student-1"
    )

    assert result.profile["student"]["institution"] is None
    assert result.profile["student"]["name"] == "Jordan Reyes"


# 4. Institution resolution is independent of career_profiles.
@pytest.mark.parametrize(
    ("kwargs", "expected_career"),
    [
        ({}, "present"),
        ({"include_career": False}, None),
        ({"career_confirmed": None}, None),
    ],
    ids=["career-present", "no-career-row", "career-unconfirmed"],
)
def test_institution_resolves_regardless_of_career_state(kwargs, expected_career):
    result = build_profile_from_supabase(FakeSupabase(_tables(**kwargs)), "uuid-student-1")

    assert result.profile["student"]["institution"] == INSTITUTION_NAME
    if expected_career is None:
        assert result.profile["career"] is None
    else:
        assert result.profile["career"] is not None


def test_student_block_is_identical_apart_from_career_presence():
    with_career = build_profile_from_supabase(
        FakeSupabase(_tables()), "uuid-student-1"
    ).profile["student"]
    without_career = build_profile_from_supabase(
        FakeSupabase(_tables(include_career=False)), "uuid-student-1"
    ).profile["student"]

    # Byte-for-byte the same student block; only `career` differs between the
    # two profiles.
    assert with_career == without_career


def test_institution_key_matches_the_demo_json_student_block():
    demo = json.loads(
        (REPO_ROOT / "data" / "students" / "student_jordanReyes.json").read_text(encoding="utf-8")
    )
    result = build_profile_from_supabase(FakeSupabase(_tables()), "uuid-student-1")

    assert "institution" in demo["student"]
    assert "institution" in result.profile["student"]
    # Same key, same type as the file-backed shape.
    assert isinstance(demo["student"]["institution"], str)
    assert isinstance(result.profile["student"]["institution"], str)
