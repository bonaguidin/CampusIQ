#!/usr/bin/env python3
"""Snapshot SMU's academic calendar from Coursedog into academic_term_dates.

Dry run is the default: the calendar is fetched and reported on, and nothing is
written anywhere. --write saves the JSON snapshot under data/reference/.
--push additionally upserts the rows into Supabase.

WHY A SNAPSHOT AND NOT A LIVE CALL
----------------------------------
Same reasoning as course_catalog, and the same shape: a per-row
source_last_checked rather than an import-batch table. A term dropdown that
renders on every visit to the Academic Record tab must not depend on a third
party's uptime, and these dates change perhaps once a year. Coursedog is also
not a contracted API -- it is the public endpoint SMU's own catalog SPA
hydrates from, gated by a Referer check rather than a key (see
data/catalog/fetch_smu_catalog.py, which uses the same host the same way).
Depending on it per-request would put an unowned dependency in the render path.

Re-run this when SMU publishes a new academic year. It is a manual one-off, not
a scheduled job. It could become one -- it is idempotent, it needs no
credentials beyond the ones the other importers already use, and it would be a
reasonable yearly cron -- but nothing schedules it today and this script does
not try to schedule itself.

TWO TRAPS IN THE SOURCE DATA, BOTH HANDLED BELOW
------------------------------------------------
1. Coursedog's `year` field is the ACADEMIC year, not the calendar year: the
   Fall 2025 term carries year="2026". Using it would file every fall term one
   year late. The year is parsed out of displayName instead, by the same
   terms.parse_term_label the transcript pipeline uses -- which also yields the
   season, so SMU's calendar and a student's transcript can never disagree
   about what "Fall 2025" means.

2. Coursedog carries placeholder rows for terms whose real dates are not set
   yet, and they are not flagged as such -- Fall 2027 is listed as
   2027-09-01 to 2027-12-31, and Spring 2028 as 2028-01-01 to 2028-05-31. Those
   are month boundaries, not a registrar's calendar (SMU's real Fall terms
   start in late August). Importing them would give upcoming-term detection
   confidently wrong dates a year from now. The window below excludes them, and
   every excluded term is REPORTED rather than silently dropped, so the next
   person to run this sees what was left behind and why.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from GradusIQ_career.transcript.terms import (  # noqa: E402
    TermParseError,
    parse_term_label,
)

OUTPUT_PATH = PROJECT_ROOT / "data" / "reference" / "smu_term_dates.json"

SCHOOL_ID = "southernmethodist_peoplesoft_direct"
TERMS_URL = f"https://app.coursedog.com/api/v1/{SCHOOL_ID}/general/terms"
CATALOG_SITE = "https://catalog.smu.edu"

# The endpoint answers 401 without the referer pair. It is a referer check, not
# authentication: no token, cookie or key is sent, and the data served is the
# same public calendar the site renders to anonymous visitors.
REQUEST_HEADERS = {
    "accept": "application/json",
    "x-requested-with": "catalog",
    "Referer": f"{CATALOG_SITE}/",
    "Origin": CATALOG_SITE,
    "User-Agent": "GradusIQ-term-dates-fetch/1.0 (academic-research)",
}

INSTITUTION_NAME = "Southern Methodist University"

# THE WINDOW. Terms starting inside it are imported; everything else is
# reported and skipped.
#
# The lower bound reaches back far enough to cover the terms live
# academic_terms rows already reference (Fall 2025, Spring 2026), so an
# existing student's past terms show dates rather than a blank line.
#
# The upper bound is the end of the 2026-2027 academic year, which is the scope
# of this phase, and -- not by coincidence -- also the last term for which
# Coursedog carries real dates. August 2027 (2027-08-05 to 2027-08-19) is
# genuine; Fall 2027 (2027-09-01 to 2027-12-31) is the first placeholder. The
# bound is stated as a date rather than as a "detect placeholders" heuristic
# because every heuristic tried here also matched at least one real term:
# placeholder rows are not reliably distinguishable by their shape alone
# (Summer 2028's 06-01 start is a month boundary; Summer 2026's 06-03 is not,
# and both are ~9 weeks long).
WINDOW_START = date(2025, 1, 1)
WINDOW_END = date(2027, 8, 31)

# Coursedog carries a sentinel row for "expected graduation unknown".
SENTINEL_YEAR_PREFIX = "999"


def stop(message: str) -> None:
    print(f"\nSTOP: {message}")
    sys.exit(1)


def fetch_terms() -> list[dict[str, Any]]:
    request = urllib.request.Request(TERMS_URL, headers=REQUEST_HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        stop(f"Coursedog returned HTTP {exc.code} for {TERMS_URL}.")
    except (urllib.error.URLError, TimeoutError) as exc:
        stop(f"Could not reach Coursedog: {exc}.")
    except json.JSONDecodeError as exc:
        stop(f"Coursedog returned a body that is not JSON: {exc}.")

    terms = payload.get("terms")
    if not isinstance(terms, list) or not terms:
        stop("Coursedog returned no terms. Refusing to write an empty snapshot.")
    return terms


def parse_iso_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def build_rows(
    terms: list[dict[str, Any]], checked_on: date
) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    """Return (rows to import, [(term label, reason skipped)])."""
    rows: list[dict[str, Any]] = []
    skipped: list[tuple[str, str]] = []
    seen: dict[tuple[int, str], str] = {}

    for term in terms:
        label = str(term.get("displayName") or term.get("id") or "?")

        if term.get("historical") is True:
            skipped.append((label, "historical"))
            continue
        if str(term.get("year") or "").startswith(SENTINEL_YEAR_PREFIX):
            skipped.append((label, "sentinel row"))
            continue

        start = parse_iso_date(term.get("startDate"))
        end = parse_iso_date(term.get("endDate"))
        if start is None or end is None:
            skipped.append((label, "missing or unparseable startDate/endDate"))
            continue
        if end < start:
            skipped.append((label, f"endDate {end} precedes startDate {start}"))
            continue
        if not (WINDOW_START <= start <= WINDOW_END):
            skipped.append((label, f"starts {start}, outside the import window"))
            continue

        try:
            # displayName, never Coursedog's `year` -- see the module docstring.
            resolved = parse_term_label(label)
        except TermParseError as exc:
            skipped.append((label, f"unparseable label: {exc}"))
            continue

        key = (resolved.year, resolved.season)
        if key in seen:
            # academic_term_dates is unique on (institution_id, year, season),
            # so a collision here would fail the upsert with a constraint error
            # halfway through. Report it instead: two Coursedog terms mapping
            # to one season means the season vocabulary needs a new value, and
            # that is a decision, not something to resolve by picking one.
            skipped.append((label, f"duplicate season {key} already taken by {seen[key]}"))
            continue
        seen[key] = label

        rows.append(
            {
                "year": resolved.year,
                "season": resolved.season,
                "label": label,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "source": "coursedog",
                "source_last_checked": checked_on.isoformat(),
                # Kept for traceability back to the source row. Not a column --
                # dropped before the database write.
                "_coursedog_term_id": str(term.get("id") or ""),
            }
        )

    rows.sort(key=lambda row: row["start_date"])
    return rows, skipped


def push(rows: list[dict[str, Any]]) -> None:
    from dotenv import load_dotenv
    from supabase import Client, create_client

    load_dotenv(PROJECT_ROOT / ".env")
    url = os.environ.get("SUPABASE_URL")
    secret_key = os.environ.get("SUPABASE_SECRET_KEY")
    if not url or not secret_key:
        stop("SUPABASE_URL and/or SUPABASE_SECRET_KEY are not set in .env.")

    client: Client = create_client(url, secret_key)

    institutions = (
        client.table("institutions").select("id,name").eq("name", INSTITUTION_NAME).execute().data
    )
    if not institutions:
        stop(f"No institution named {INSTITUTION_NAME!r} exists.")
    if len(institutions) > 1:
        stop(f"{len(institutions)} institutions named {INSTITUTION_NAME!r}; refusing to guess.")
    institution_id = institutions[0]["id"]

    created = updated = 0
    for row in rows:
        payload = {key: value for key, value in row.items() if not key.startswith("_")}
        payload["institution_id"] = institution_id

        # Application-level upsert on the natural key, matching
        # scripts/import_students.py. academic_term_dates DOES carry a real
        # unique (institution_id, year, season) constraint, so a native
        # on_conflict would work here -- but check-then-write keeps the
        # create/update counts this script reports honest, which a blind upsert
        # cannot do.
        existing = (
            client.table("academic_term_dates")
            .select("id")
            .eq("institution_id", institution_id)
            .eq("year", row["year"])
            .eq("season", row["season"])
            .execute()
            .data
        )
        if existing:
            payload["updated_at"] = "now()"
            client.table("academic_term_dates").update(payload).eq(
                "id", existing[0]["id"]
            ).execute()
            updated += 1
        else:
            client.table("academic_term_dates").insert(payload).execute()
            created += 1

    print(f"\npushed to Supabase: {created} created, {updated} updated")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write", action="store_true", help=f"save the JSON snapshot to {OUTPUT_PATH}"
    )
    parser.add_argument(
        "--push", action="store_true", help="upsert the rows into Supabase (implies --write)"
    )
    args = parser.parse_args()

    checked_on = date.today()
    terms = fetch_terms()
    rows, skipped = build_rows(terms, checked_on)

    print(f"Coursedog returned {len(terms)} terms for {SCHOOL_ID}.")
    print(f"Import window: {WINDOW_START} .. {WINDOW_END}\n")
    print(f"{len(rows)} term(s) to import:")
    for row in rows:
        print(
            f"  {row['start_date']} .. {row['end_date']}  "
            f"{row['year']} {row['season']:<7} {row['label']}"
        )

    # Every exclusion is printed. The placeholder-date problem described in the
    # module docstring is only visible here.
    in_window_skips = [item for item in skipped if "outside the import window" not in item[1]]
    print(f"\n{len(skipped)} term(s) skipped ({len(in_window_skips)} for reasons other than the window):")
    for label, reason in skipped:
        print(f"  {label}: {reason}")

    if not rows:
        stop("Nothing to import. Refusing to write an empty snapshot.")

    if args.write or args.push:
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        snapshot = {
            "source": TERMS_URL,
            "institution": INSTITUTION_NAME,
            "fetched_on": checked_on.isoformat(),
            "window": {"start": WINDOW_START.isoformat(), "end": WINDOW_END.isoformat()},
            "terms": rows,
        }
        OUTPUT_PATH.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
        print(f"\nwrote {OUTPUT_PATH.relative_to(PROJECT_ROOT)}")
    else:
        print("\nDry run. Nothing written. Pass --write to save, --push to also upsert.")

    if args.push:
        push(rows)


if __name__ == "__main__":
    main()
