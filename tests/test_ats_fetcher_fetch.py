"""Unit tests for data/ats_fetcher/fetch_postings.py's per-ATS adapters,
clean(), and main()'s dispatch/logging. Mirrors the monkeypatch-injection
style already used in tests/test_job_postings_clients.py -- no real network
calls; get_json() is monkeypatched at the module level instead of injecting
a session object, since fetch_postings.py calls urllib directly rather than
through an injectable client.

Fixture payloads for Greenhouse (PMG) and Lever (Match Group) are modeled on
the real, already-confirmed shapes noted in data/ats_fetcher/employers.json
("confirmed 70 postings" / "confirmed 82 postings"). Ashby and SmartRecruiters
fixtures are modeled on their published job-board API doc sample shapes,
since neither has a confirmed employer in employers.json yet.
"""

import csv
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "data" / "ats_fetcher"))

import fetch_postings  # noqa: E402


# ---------------------------------------------------------------------------
# get_json() call-queue helper
# ---------------------------------------------------------------------------

class QueuedGetJson:
    """Fake for fetch_postings.get_json(): returns responses[i] on the i-th
    call, and records every URL requested. Raises if more calls happen than
    responses were queued, or the queue can be exhausted deliberately to
    simulate a detail-fetch failure via `exc_on`.
    """

    def __init__(self, responses, exc_on=None):
        self.responses = list(responses)
        self.exc_on = exc_on or {}
        self.calls = []

    def __call__(self, url):
        i = len(self.calls)
        self.calls.append(url)
        if i in self.exc_on:
            raise self.exc_on[i]
        return self.responses[i]


# ---------------------------------------------------------------------------
# clean()
# ---------------------------------------------------------------------------

def test_clean_double_unescapes_greenhouse_style_html():
    # Greenhouse hands back HTML-escaped HTML: "&amp;lt;p&amp;gt;" for "<p>".
    raw = "&amp;lt;p&amp;gt;Build things&amp;lt;/p&amp;gt;"
    assert fetch_postings.clean(raw) == "Build things"


def test_clean_strips_tags_and_collapses_whitespace():
    raw = "<p>Line one</p>\n\n\n<ul><li>Bullet</li></ul>   trailing   spaces"
    result = fetch_postings.clean(raw)
    assert "<" not in result
    assert "\n\n" not in result
    assert "   " not in result


def test_clean_handles_none_and_empty():
    assert fetch_postings.clean(None) == ""
    assert fetch_postings.clean("") == ""


def test_clean_converts_nbsp_to_space():
    assert "\xa0" not in fetch_postings.clean("Requirements:\xa0SQL")


# ---------------------------------------------------------------------------
# fetch_greenhouse
# ---------------------------------------------------------------------------

def _gh_payload(jobs):
    return {"jobs": jobs}


def test_fetch_greenhouse_happy_path(monkeypatch):
    payload = _gh_payload([{
        "id": 8496729002,
        "title": "Marketing Analyst",
        "location": {"name": "Dallas, TX"},
        "absolute_url": "https://job-boards.greenhouse.io/pmg/jobs/8496729002",
        "first_published": "2026-08-01T00:00:00Z",
        "content": "&lt;p&gt;Own reporting for client accounts.&lt;/p&gt;",
    }])
    monkeypatch.setattr(fetch_postings, "get_json", QueuedGetJson([payload]))

    out, warnings = fetch_postings.fetch_greenhouse("pmg")

    assert warnings == 0
    assert len(out) == 1
    row = out[0]
    assert row["external_id"] == "8496729002"
    assert row["title"] == "Marketing Analyst"
    assert row["location"] == "Dallas, TX"
    assert row["posted_at"] == "2026-08-01"
    assert row["description"] == "Own reporting for client accounts."


def test_fetch_greenhouse_falls_back_to_updated_at(monkeypatch):
    payload = _gh_payload([{
        "id": 1,
        "title": "Analyst",
        "location": {"name": "Remote"},
        "absolute_url": "https://x",
        "updated_at": "2026-07-15T12:00:00Z",
        "content": "",
    }])
    monkeypatch.setattr(fetch_postings, "get_json", QueuedGetJson([payload]))

    out, _ = fetch_postings.fetch_greenhouse("pmg")

    assert out[0]["posted_at"] == "2026-07-15"


def test_fetch_greenhouse_null_title_does_not_crash(monkeypatch):
    # Regression for the null-guard fix: dict.get(key, default) only applies
    # the default when the key is absent, not when the API sends an
    # explicit null. Before the fix this raised AttributeError on .strip().
    payload = _gh_payload([{
        "id": 2,
        "title": None,
        "location": {"name": None},
        "absolute_url": "https://x",
        "content": "",
    }])
    monkeypatch.setattr(fetch_postings, "get_json", QueuedGetJson([payload]))

    out, _ = fetch_postings.fetch_greenhouse("pmg")

    assert out[0]["title"] == ""
    assert out[0]["location"] == ""


def test_fetch_greenhouse_null_location_object_does_not_crash(monkeypatch):
    payload = _gh_payload([{
        "id": 3,
        "title": "Analyst",
        "location": None,
        "absolute_url": "https://x",
        "content": "",
    }])
    monkeypatch.setattr(fetch_postings, "get_json", QueuedGetJson([payload]))

    out, _ = fetch_postings.fetch_greenhouse("pmg")

    assert out[0]["location"] == ""


def test_fetch_greenhouse_malformed_top_level_shape_returns_empty(monkeypatch):
    # No "jobs" key at all -- treated as zero postings, not a crash.
    monkeypatch.setattr(fetch_postings, "get_json", QueuedGetJson([{"error": "not found"}]))

    out, warnings = fetch_postings.fetch_greenhouse("pmg")

    assert out == []
    assert warnings == 0


# ---------------------------------------------------------------------------
# fetch_lever
# ---------------------------------------------------------------------------

def test_fetch_lever_happy_path_joins_description_and_additional(monkeypatch):
    payload = [{
        "id": "abc123",
        "text": "Data Analyst",
        "categories": {"location": "Dallas, TX"},
        "hostedUrl": "https://jobs.lever.co/matchgroup/abc123",
        "createdAt": 1750000000000,
        "descriptionPlain": "Own the weekly reporting cadence.",
        "additionalPlain": "Requires SQL and Excel.",
    }]
    monkeypatch.setattr(fetch_postings, "get_json", QueuedGetJson([payload]))

    out, warnings = fetch_postings.fetch_lever("matchgroup")

    assert warnings == 0
    row = out[0]
    assert row["external_id"] == "abc123"
    assert row["title"] == "Data Analyst"
    assert "Own the weekly reporting cadence." in row["description"]
    assert "Requires SQL and Excel." in row["description"]


def test_fetch_lever_uses_text_field_not_title(monkeypatch):
    # Lever's title lives under "text", not "title" -- a bare .get("title")
    # would silently return "" for every posting.
    payload = [{"id": "1", "text": "Should be used", "title": "Should NOT be used"}]
    monkeypatch.setattr(fetch_postings, "get_json", QueuedGetJson([payload]))

    out, _ = fetch_postings.fetch_lever("matchgroup")

    assert out[0]["title"] == "Should be used"


def test_fetch_lever_falls_back_to_cleaned_html_description(monkeypatch):
    payload = [{
        "id": "1",
        "text": "Analyst",
        "description": "&lt;p&gt;Fallback HTML desc&lt;/p&gt;",
        "additional": "",
    }]
    monkeypatch.setattr(fetch_postings, "get_json", QueuedGetJson([payload]))

    out, _ = fetch_postings.fetch_lever("matchgroup")

    assert "Fallback HTML desc" in out[0]["description"]


def test_fetch_lever_missing_created_at_leaves_posted_at_blank(monkeypatch):
    payload = [{"id": "1", "text": "Analyst"}]
    monkeypatch.setattr(fetch_postings, "get_json", QueuedGetJson([payload]))

    out, _ = fetch_postings.fetch_lever("matchgroup")

    assert out[0]["posted_at"] == ""


def test_fetch_lever_malformed_top_level_shape_raises(monkeypatch):
    # Lever's endpoint returns a bare list; a dict-shaped error payload
    # (e.g. {"code": "not_found"}) iterates as string keys and fails loudly
    # via AttributeError rather than silently producing bad rows.
    monkeypatch.setattr(fetch_postings, "get_json", QueuedGetJson([{"code": "not_found"}]))

    with pytest.raises(AttributeError):
        fetch_postings.fetch_lever("matchgroup")


# ---------------------------------------------------------------------------
# fetch_ashby
# ---------------------------------------------------------------------------

def test_fetch_ashby_prefers_description_plain(monkeypatch):
    payload = {"jobs": [{
        "id": "j1",
        "title": "Business Analyst",
        "location": "Dallas, TX",
        "jobUrl": "https://jobs.ashbyhq.com/x/j1",
        "publishedAt": "2026-08-05T00:00:00.000Z",
        "descriptionPlain": "Plain text wins over HTML.",
        "descriptionHtml": "<p>Should not be used</p>",
    }]}
    monkeypatch.setattr(fetch_postings, "get_json", QueuedGetJson([payload]))

    out, warnings = fetch_postings.fetch_ashby("x")

    assert warnings == 0
    assert out[0]["description"] == "Plain text wins over HTML."
    assert out[0]["posted_at"] == "2026-08-05"


def test_fetch_ashby_falls_back_to_cleaned_html(monkeypatch):
    payload = {"jobs": [{
        "id": "j2",
        "title": "Analyst",
        "descriptionHtml": "&lt;p&gt;Only HTML available&lt;/p&gt;",
    }]}
    monkeypatch.setattr(fetch_postings, "get_json", QueuedGetJson([payload]))

    out, _ = fetch_postings.fetch_ashby("x")

    assert out[0]["description"] == "Only HTML available"


def test_fetch_ashby_null_location_does_not_crash(monkeypatch):
    payload = {"jobs": [{"id": "j3", "title": "Analyst", "location": None}]}
    monkeypatch.setattr(fetch_postings, "get_json", QueuedGetJson([payload]))

    out, _ = fetch_postings.fetch_ashby("x")

    assert out[0]["location"] == ""


# ---------------------------------------------------------------------------
# fetch_smartrecruiters -- pagination and detail-fetch failure
# ---------------------------------------------------------------------------

def _sr_list_page(items, total_found):
    return {"content": items, "totalFound": total_found}


def _sr_detail(job_desc="", qualifications="", additional=""):
    return {"jobAd": {"sections": {
        "jobDescription": {"text": job_desc},
        "qualifications": {"text": qualifications},
        "additionalInformation": {"text": additional},
    }}}


def test_fetch_smartrecruiters_happy_path_single_page(monkeypatch):
    list_page = _sr_list_page(
        [{
            "id": "sr1",
            "name": "Financial Analyst",
            "location": {"city": "Dallas", "region": "TX"},
            "ref": "https://jobs.smartrecruiters.com/x/sr1",
            "releasedDate": "2026-08-10T00:00:00Z",
        }],
        total_found=1,
    )
    detail = _sr_detail(job_desc="Own the FP&A model.", qualifications="Excel required.")
    monkeypatch.setattr(fetch_postings, "get_json", QueuedGetJson([list_page, detail]))
    monkeypatch.setattr(fetch_postings.time, "sleep", lambda *_: None)

    out, warnings = fetch_postings.fetch_smartrecruiters("x")

    assert warnings == 0
    assert len(out) == 1
    row = out[0]
    assert row["external_id"] == "sr1"
    assert row["title"] == "Financial Analyst"
    assert row["location"] == "Dallas, TX"
    assert "Own the FP&A model." in row["description"]
    assert "Excel required." in row["description"]


def test_fetch_smartrecruiters_uses_name_field_not_title(monkeypatch):
    list_page = _sr_list_page([{"id": "1", "name": "Correct", "title": "Wrong"}], total_found=1)
    monkeypatch.setattr(fetch_postings, "get_json", QueuedGetJson([list_page, _sr_detail()]))
    monkeypatch.setattr(fetch_postings.time, "sleep", lambda *_: None)

    out, _ = fetch_postings.fetch_smartrecruiters("x")

    assert out[0]["title"] == "Correct"


def test_fetch_smartrecruiters_paginates_across_pages(monkeypatch):
    page1 = _sr_list_page([{"id": "1", "name": "A"}], total_found=2)
    page2 = _sr_list_page([{"id": "2", "name": "B"}], total_found=2)
    responses = QueuedGetJson([page1, _sr_detail(), page2, _sr_detail()])
    monkeypatch.setattr(fetch_postings, "get_json", responses)
    monkeypatch.setattr(fetch_postings.time, "sleep", lambda *_: None)

    out, warnings = fetch_postings.fetch_smartrecruiters("x")

    assert warnings == 0
    assert [row["external_id"] for row in out] == ["1", "2"]
    # offset advances by len(items) each page: 0 then 1.
    assert "offset=0" in responses.calls[0]
    assert "offset=1" in responses.calls[2]


def test_fetch_smartrecruiters_stops_on_empty_page(monkeypatch):
    empty_first_page = _sr_list_page([], total_found=0)
    monkeypatch.setattr(fetch_postings, "get_json", QueuedGetJson([empty_first_page]))
    monkeypatch.setattr(fetch_postings.time, "sleep", lambda *_: None)

    out, warnings = fetch_postings.fetch_smartrecruiters("x")

    assert out == []
    assert warnings == 0


def test_fetch_smartrecruiters_detail_fetch_failure_drops_posting_and_counts_warning(monkeypatch):
    # Regression for the detail-fetch-failure fix: a failed detail call must
    # not produce a description="" row counted as successful. It should be
    # dropped from output and tallied in warnings instead.
    list_page = _sr_list_page(
        [{"id": "ok1", "name": "Keeps"}, {"id": "fails1", "name": "Drops"}],
        total_found=2,
    )
    responses = QueuedGetJson(
        [list_page, _sr_detail(job_desc="fine"), None],
        exc_on={2: RuntimeError("detail fetch boom")},
    )
    monkeypatch.setattr(fetch_postings, "get_json", responses)
    monkeypatch.setattr(fetch_postings.time, "sleep", lambda *_: None)

    out, warnings = fetch_postings.fetch_smartrecruiters("x")

    assert warnings == 1
    assert [row["external_id"] for row in out] == ["ok1"]


def test_fetch_smartrecruiters_multiple_detail_failures_all_counted(monkeypatch):
    list_page = _sr_list_page(
        [{"id": "1", "name": "A"}, {"id": "2", "name": "B"}],
        total_found=2,
    )
    responses = QueuedGetJson(
        [list_page, None, None],
        exc_on={1: RuntimeError("boom 1"), 2: RuntimeError("boom 2")},
    )
    monkeypatch.setattr(fetch_postings, "get_json", responses)
    monkeypatch.setattr(fetch_postings.time, "sleep", lambda *_: None)

    out, warnings = fetch_postings.fetch_smartrecruiters("x")

    assert out == []
    assert warnings == 2


def test_fetch_smartrecruiters_missing_location_fields_do_not_crash(monkeypatch):
    list_page = _sr_list_page([{"id": "1", "name": "A", "location": {}}], total_found=1)
    monkeypatch.setattr(fetch_postings, "get_json", QueuedGetJson([list_page, _sr_detail()]))
    monkeypatch.setattr(fetch_postings.time, "sleep", lambda *_: None)

    out, _ = fetch_postings.fetch_smartrecruiters("x")

    assert out[0]["location"] == ""


# ---------------------------------------------------------------------------
# main() -- dispatch, status encoding, pull_log.csv shape
# ---------------------------------------------------------------------------

def _run_main(monkeypatch, tmp_path, employers, args=("--probe",)):
    employers_path = tmp_path / "employers.json"
    employers_path.write_text(__import__("json").dumps(employers))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys, "argv",
        ["fetch_postings.py", "--employers", str(employers_path), *args],
    )
    monkeypatch.setattr(fetch_postings.time, "sleep", lambda *_: None)
    fetch_postings.main()
    with open(tmp_path / "pull_log.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_main_skips_unsupported_ats(monkeypatch, tmp_path, capsys):
    log_rows = _run_main(
        monkeypatch, tmp_path,
        [{"name": "Acme", "ats": "recruitee", "slug": "acme"}],
    )
    assert log_rows == []
    assert "SKIP unsupported ats 'recruitee'" in capsys.readouterr().out


def test_main_encodes_partial_status_from_smartrecruiters_warnings(monkeypatch, tmp_path):
    def fake_smartrecruiters(slug):
        return [{"external_id": "1", "title": "A", "location": "", "url": "",
                  "posted_at": "", "description": ""}], 2

    monkeypatch.setattr(fetch_postings, "ADAPTERS",
                         {**fetch_postings.ADAPTERS, "smartrecruiters": fake_smartrecruiters})

    log_rows = _run_main(
        monkeypatch, tmp_path,
        [{"name": "Acme", "ats": "smartrecruiters", "slug": "acme"}],
    )

    assert log_rows[0]["status"] == "partial_2_detail_failures"
    assert log_rows[0]["count"] == "1"


def test_main_ok_status_when_no_warnings(monkeypatch, tmp_path):
    def fake_greenhouse(slug):
        return [], 0

    monkeypatch.setattr(fetch_postings, "ADAPTERS",
                         {**fetch_postings.ADAPTERS, "greenhouse": fake_greenhouse})

    log_rows = _run_main(
        monkeypatch, tmp_path,
        [{"name": "Acme", "ats": "greenhouse", "slug": "acme"}],
    )

    assert log_rows[0]["status"] == "ok"
