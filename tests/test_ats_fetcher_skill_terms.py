"""Unit tests for data/ats_fetcher/build_skill_terms.py: term normalization,
O*NET vocabulary loading, flag reasoning, and the generate/filter CSV
contracts. No network involved -- these are pure CSV/string transforms.
"""

import csv
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "data" / "ats_fetcher"))

import build_skill_terms as bst  # noqa: E402


# ---------------------------------------------------------------------------
# normalize_term
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Salesforce software", "Salesforce"),
        ("Project management systems", "Project management"),
        ("Microsoft Excel", "Microsoft Excel"),
        ("Accounting program", "Accounting"),
        ("  Tableau  ", "Tableau"),
    ],
)
def test_normalize_term_strips_known_suffixes(raw, expected):
    assert bst.normalize_term(raw) == expected


def test_normalize_term_strips_repeated_suffixes():
    # STRIP_SUFFIXES loop repeats until no more suffixes match, so a term
    # with two stackable suffixes ("... tool system") should fully collapse,
    # not just strip the outermost one.
    assert bst.normalize_term("Analytics tool system") == "Analytics"


def test_normalize_term_no_suffix_is_unchanged():
    assert bst.normalize_term("Python") == "Python"


def test_normalize_term_bare_suffix_word_is_unchanged():
    # STRIP_SUFFIXES only matches a suffix preceded by whitespace (\s+suffix$),
    # and normalize_term's first step is .strip() -- so a term that is
    # *only* a suffix word, with nothing before it, never has a leading
    # space to strip and is left as-is rather than reduced to "".
    assert bst.normalize_term("software") == "software"


# ---------------------------------------------------------------------------
# load_skill_terms
# ---------------------------------------------------------------------------

def _write_csv(path, rows, fieldnames):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_load_skill_terms_dedupes_by_normalized_key(tmp_path):
    path = tmp_path / "skills.csv"
    _write_csv(path, [
        {"product": "Excel software", "category": "Office", "hot_technology": "N"},
        {"product": "Excel", "category": "Office", "hot_technology": "N"},
    ], fieldnames=["product", "category", "hot_technology"])

    terms = bst.load_skill_terms(path)

    assert len(terms) == 1
    assert terms[0]["term"] == "Excel"


def test_load_skill_terms_skips_blank_rows(tmp_path):
    path = tmp_path / "skills.csv"
    _write_csv(path, [
        {"product": "", "category": "Office", "hot_technology": "N"},
        {"product": "SQL", "category": "Data", "hot_technology": "Y"},
    ], fieldnames=["product", "category", "hot_technology"])

    terms = bst.load_skill_terms(path)

    assert [t["term"] for t in terms] == ["SQL"]


def test_load_skill_terms_reports_zero_skipped_when_none_empty(tmp_path, capsys):
    # The "skipped N rows that normalized to empty" branch exists in the
    # source but is effectively unreachable via CSV input under the current
    # normalize_term() regex (see test_normalize_term_bare_suffix_word_is_
    # unchanged): raw_term is stripped before normalize_term ever runs, and
    # a bare suffix word has no leading whitespace left to strip. This test
    # just documents that the ordinary path doesn't trip it.
    path = tmp_path / "skills.csv"
    _write_csv(path, [
        {"product": "Python", "category": "Dev", "hot_technology": "Y"},
    ], fieldnames=["product", "category", "hot_technology"])

    terms = bst.load_skill_terms(path)

    assert [t["term"] for t in terms] == ["Python"]
    assert "skipped" not in capsys.readouterr().out


def test_load_skill_terms_preserves_category_and_hot_technology(tmp_path):
    path = tmp_path / "skills.csv"
    _write_csv(path, [
        {"product": "Power BI", "category": "Analytics", "hot_technology": "Y"},
    ], fieldnames=["product", "category", "hot_technology"])

    terms = bst.load_skill_terms(path)

    assert terms[0]["category"] == "Analytics"
    assert terms[0]["hot_technology"] == "Y"


# ---------------------------------------------------------------------------
# flag_reason
# ---------------------------------------------------------------------------

def test_flag_reason_short_token():
    assert bst.flag_reason("Go", 0.01) == "short token"


def test_flag_reason_common_word():
    assert bst.flag_reason("design", 0.01) == "common word"


def test_flag_reason_high_fire_rate():
    assert bst.flag_reason("Analysis Skill", 0.5) == "high fire rate"


def test_flag_reason_none_when_clean():
    assert bst.flag_reason("Salesforce", 0.02) == ""


def test_flag_reason_short_token_takes_priority_over_fire_rate():
    # "R" is both <= SHORT_TOKEN_MAX_LEN and would clear the fire-rate bar;
    # short-token check runs first.
    assert bst.flag_reason("R", 0.9) == "short token"


# ---------------------------------------------------------------------------
# run_filter (blank-decision refusal, Y/N split, output shape)
# ---------------------------------------------------------------------------

def _write_review_csv(path, rows):
    fieldnames = ["term", "category", "hot_technology", "fire_count",
                  "fire_rate", "example_1", "example_2", "flag_reason", "keep"]
    _write_csv(path, rows, fieldnames)


def test_run_filter_refuses_on_blank_keep_decision(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(bst, "REVIEW_PATH", tmp_path / "review.csv")
    monkeypatch.setattr(bst, "FILTERED_PATH", tmp_path / "filtered.csv")
    _write_review_csv(bst.REVIEW_PATH, [
        {"term": "SQL", "category": "Data", "hot_technology": "Y", "fire_count": "5",
         "fire_rate": "0.1", "example_1": "", "example_2": "", "flag_reason": "", "keep": ""},
    ])

    with pytest.raises(SystemExit):
        bst.run_filter()

    assert "no keep decision yet" in capsys.readouterr().out
    assert not bst.FILTERED_PATH.exists()


def test_run_filter_writes_only_y_rows_with_expected_columns(tmp_path, monkeypatch):
    monkeypatch.setattr(bst, "REVIEW_PATH", tmp_path / "review.csv")
    monkeypatch.setattr(bst, "FILTERED_PATH", tmp_path / "filtered.csv")
    _write_review_csv(bst.REVIEW_PATH, [
        {"term": "SQL", "category": "Data", "hot_technology": "Y", "fire_count": "5",
         "fire_rate": "0.1", "example_1": "", "example_2": "", "flag_reason": "", "keep": "Y"},
        {"term": "analysis", "category": "General", "hot_technology": "N", "fire_count": "50",
         "fire_rate": "0.6", "example_1": "", "example_2": "", "flag_reason": "high fire rate",
         "keep": "N"},
    ])

    bst.run_filter()

    with bst.FILTERED_PATH.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 1
    assert rows[0] == {"term": "SQL", "category": "Data", "hot_technology": "Y"}


def test_run_filter_missing_review_file_exits(tmp_path, monkeypatch):
    monkeypatch.setattr(bst, "REVIEW_PATH", tmp_path / "does_not_exist.csv")
    monkeypatch.setattr(bst, "FILTERED_PATH", tmp_path / "filtered.csv")

    with pytest.raises(SystemExit):
        bst.run_filter()


# ---------------------------------------------------------------------------
# run_generate -- end-to-end scan against fixture postings
# ---------------------------------------------------------------------------

def test_run_generate_computes_fire_count_and_rate(tmp_path, monkeypatch):
    monkeypatch.setattr(bst, "SKILLS_PATH", tmp_path / "skills.csv")
    monkeypatch.setattr(bst, "POSTINGS_PATH", tmp_path / "postings.csv")
    monkeypatch.setattr(bst, "REVIEW_PATH", tmp_path / "review.csv")

    _write_csv(bst.SKILLS_PATH, [
        {"product": "SQL", "category": "Data", "hot_technology": "Y"},
        {"product": "Salesforce", "category": "CRM", "hot_technology": "N"},
    ], fieldnames=["product", "category", "hot_technology"])

    _write_csv(bst.POSTINGS_PATH, [
        {"description": "Must know SQL and reporting tools."},
        {"description": "General office duties, no technical requirements."},
    ], fieldnames=["description"])

    bst.run_generate()

    with bst.REVIEW_PATH.open(newline="", encoding="utf-8") as f:
        rows = {r["term"]: r for r in csv.DictReader(f)}

    assert rows["SQL"]["fire_count"] == "1"
    assert rows["SQL"]["fire_rate"] == "0.5000"
    assert rows["Salesforce"]["fire_count"] == "0"
    assert rows["Salesforce"]["keep"] == "Y"


def test_run_generate_exits_when_postings_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(bst, "SKILLS_PATH", tmp_path / "skills.csv")
    monkeypatch.setattr(bst, "POSTINGS_PATH", tmp_path / "postings.csv")
    _write_csv(bst.SKILLS_PATH, [{"product": "SQL", "category": "Data", "hot_technology": "Y"}],
               fieldnames=["product", "category", "hot_technology"])

    with pytest.raises(SystemExit):
        bst.run_generate()
