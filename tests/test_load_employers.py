"""Tests for the DFW employer list loader.

Reads the real CSV where it exists, since the point of most of these is that
the file's actual state -- 44 employers, almost no ATS data, no slugs at all --
is what the loader has to report honestly rather than paper over.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "job_postings"))

from load_employers import (  # noqa: E402
    EmployerCsvError,
    fetchable,
    parse_rows,
    render_report,
)

CSV = REPO_ROOT / "data" / "job_postings" / "dfw_employers_ats.csv"

HEADER = ("priority,employer,sector,dfw_location,domain,"
          "target_role_families,ats,slug,checked_date,notes\n")


def write_csv(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "employers.csv"
    p.write_text(HEADER + body, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Shape and parsing
# ---------------------------------------------------------------------------

def test_missing_columns_are_fatal(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("employer,sector\nAcme,Tech\n", encoding="utf-8")
    with pytest.raises(EmployerCsvError, match="missing expected column"):
        parse_rows(p)


def test_example_row_is_skipped(tmp_path):
    p = write_csv(tmp_path,
        "EXAMPLE,EXAMPLE CO — delete this row,S,Plano,e.com,Marketing,greenhouse,ex,2026-08-17,note\n"
        "1,Acme,Finance,Dallas,acme.com,Financial analyst,,,,\n")
    rows, _ = parse_rows(p)
    assert [r["name"] for r in rows] == ["Acme"]


def test_role_families_split_on_semicolon_not_comma(tmp_path):
    """The values contain commas ('risk/compliance, junior') so the delimiter
    has to be the semicolon the source actually uses."""
    p = write_csv(tmp_path,
        '1,Acme,Finance,Dallas,acme.com,"Financial analyst; client service associate; risk/compliance",,,,\n')
    rows, _ = parse_rows(p)
    assert rows[0]["target_role_families"] == [
        "Financial analyst", "client service associate", "risk/compliance",
    ]


def test_blank_fields_become_none_not_empty_string(tmp_path):
    """An empty CSV cell is absent data. Writing '' would make a NOT NULL-ish
    value out of nothing and defeat the 'has a slug?' check."""
    p = write_csv(tmp_path, "1,Acme,Finance,Dallas,acme.com,Analyst,,,,\n")
    rows, _ = parse_rows(p)
    assert rows[0]["slug"] is None
    assert rows[0]["ats_platform"] is None
    assert rows[0]["checked_date"] is None


def test_unknown_ats_is_nulled_with_a_warning(tmp_path):
    """The table's check constraint would reject it, so storing it would fail
    the whole load for one bad cell."""
    p = write_csv(tmp_path, "1,Acme,Finance,Dallas,acme.com,Analyst,workday,acme,,\n")
    rows, warnings = parse_rows(p)
    assert rows[0]["ats_platform"] is None
    assert any("workday" in w for w in warnings)


def test_known_ats_is_lowercased(tmp_path):
    p = write_csv(tmp_path, "1,Acme,Finance,Dallas,acme.com,Analyst,Greenhouse,acme,,\n")
    rows, _ = parse_rows(p)
    assert rows[0]["ats_platform"] == "greenhouse"


def test_row_without_a_name_is_skipped(tmp_path):
    p = write_csv(tmp_path, "1,,Finance,Dallas,acme.com,Analyst,,,,\n")
    rows, warnings = parse_rows(p)
    assert rows == []
    assert any("no employer name" in w for w in warnings)


def test_duplicate_employer_is_skipped_case_insensitively(tmp_path):
    p = write_csv(tmp_path,
        "1,Acme,Finance,Dallas,acme.com,Analyst,,,,\n"
        "2,ACME,Finance,Plano,acme.com,Analyst,,,,\n")
    rows, warnings = parse_rows(p)
    assert len(rows) == 1
    assert any("duplicate" in w for w in warnings)


def test_priority_parses_and_survives_junk(tmp_path):
    p = write_csv(tmp_path,
        "3,Acme,Finance,Dallas,acme.com,Analyst,,,,\n"
        "high,Beta,Finance,Dallas,beta.com,Analyst,,,,\n")
    rows, _ = parse_rows(p)
    assert rows[0]["priority"] == 3
    assert rows[1]["priority"] is None


# ---------------------------------------------------------------------------
# Fetchability -- the thing the report must not overstate
# ---------------------------------------------------------------------------

def test_fetchable_requires_both_ats_and_slug(tmp_path):
    p = write_csv(tmp_path,
        "1,BothMissing,F,Dallas,a.com,Analyst,,,,\n"
        "1,AtsOnly,F,Dallas,b.com,Analyst,lever,,,\n"
        "1,SlugOnly,F,Dallas,c.com,Analyst,,someslug,,\n"
        "1,Complete,F,Dallas,d.com,Analyst,lever,goodslug,,\n")
    rows, _ = parse_rows(p)
    assert [r["name"] for r in fetchable(rows)] == ["Complete"]


def test_report_says_plainly_when_nothing_is_fetchable(tmp_path):
    p = write_csv(tmp_path, "1,Acme,Finance,Dallas,acme.com,Analyst,lever,,,\n")
    rows, warnings = parse_rows(p)
    out = render_report(rows, warnings, dry_run=True)
    assert "actually fetchable      0" in out
    assert "cannot be fetched yet" in out


# ---------------------------------------------------------------------------
# The real file
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not CSV.exists(), reason="employer CSV not in the repo")
def test_real_csv_parses_to_44_employers():
    rows, warnings = parse_rows(CSV)
    assert len(rows) == 44, f"expected 44 real employers, got {len(rows)}"
    assert not warnings, f"unexpected warnings: {warnings}"


@pytest.mark.skipif(not CSV.exists(), reason="employer CSV not in the repo")
def test_real_csv_has_no_fetchable_employers_yet():
    """Pins the current state so it is visible rather than assumed. When slugs
    get filled in, this test failing is the signal that they did."""
    rows, _ = parse_rows(CSV)
    assert fetchable(rows) == []
    assert sum(1 for r in rows if r["slug"]) == 0
    assert sum(1 for r in rows if r["ats_platform"]) == 1


@pytest.mark.skipif(not CSV.exists(), reason="employer CSV not in the repo")
def test_real_csv_every_employer_has_a_domain():
    """The domain is what a slug lookup starts from, so its absence would make
    an employer unresearchable rather than merely unfetched."""
    rows, _ = parse_rows(CSV)
    assert [r["name"] for r in rows if not r["domain"]] == []
