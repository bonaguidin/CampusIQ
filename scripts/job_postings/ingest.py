#!/usr/bin/env python3
"""Nightly postings ingest -- fetch, normalize, dedup, store.

Loops the target roles, asks each vendor for that role in the DFW metro,
normalizes every response into one row shape, resolves cross-source identity,
and upserts. Every call writes a job_posting_fetch_log row whether it worked
or not.

DRY RUN IS THE DEFAULT, same as the vendor clients this builds on. Without
--live nothing is fetched and nothing is written; the planned calls are
printed instead. Both free tiers are small -- Adzuna ~1,000/mo and JSearch
~200/mo across 14 roles -- so an accidental run is a real cost, not a
nuisance.

CADENCE IS PER VENDOR, NOT GLOBAL. Adzuna's ~70 calls/role/month affords a
nightly fetch. JSearch's ~14 cannot: nightly would burn the month's quota in
two weeks. The integration spec narrows JSearch further still, to
LinkedIn-source confirmation only, after a live 2026-08-17 test returned zero
results on both vendors for the role it was meant to gap-fill. So JSearch is
opt-in per run rather than part of the nightly sweep.

WHAT THIS CANNOT DO YET
-----------------------
The tables do not exist. supabase/migrations/20260817210000 is staged and
says not to apply it until Deepak has reviewed. So --live --write will fail
against a real project until that lands; --live on its own fetches and
normalizes without writing, which is the useful shape for confirming the
field maps in normalize.py.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

from errors import JobPostingConfigError, JobPostingRequestError  # noqa: E402
from identity import identity_keys  # noqa: E402
from normalize import (  # noqa: E402
    NormalizationError,
    describe_shape,
    normalize_response,
)

ROLE_REQUIREMENTS = REPO_ROOT / "data" / "role_requirements.json"

POSTINGS_TABLE = "job_postings"
FETCH_LOG_TABLE = "job_posting_fetch_log"
CLUSTERS_TABLE = "posting_clusters"
MERGES_TABLE = "posting_cluster_merges"

UPSERT_CONFLICT = "source,source_job_id"

# Rows per vendor call. Small on purpose -- one call returns one page, and a
# bigger page does not cost more quota but does cost more to normalize wrongly
# while the field maps are unconfirmed.
DEFAULT_PAGE_SIZE = 20

DEFAULT_WHERE = "Dallas"
DEFAULT_DISTANCE_MILES = 30

# See the module docstring. Adzuna alone is the nightly sweep.
NIGHTLY_SOURCES = ("adzuna",)


def load_target_roles() -> list[str]:
    """The 14 roles, from the file that already defines them.

    Deliberately not a second list. role_requirements.json is what GAP and FIT
    already key off, and a role string that exists here but not there would
    produce postings nothing can ever retrieve.
    """
    with ROLE_REQUIREMENTS.open(encoding="utf-8") as f:
        data = json.load(f)
    return [k for k in data if k != "_notes"]


@dataclass
class FetchOutcome:
    """One vendor call. Becomes exactly one job_posting_fetch_log row."""

    source: str
    target_role: str
    results_count: int = 0
    quota_used: int = 0
    status: str = "success"
    error_detail: str | None = None
    rows: list[dict] = field(default_factory=list)
    normalization_errors: list[str] = field(default_factory=list)

    def log_row(self) -> dict:
        return {
            "source": self.source,
            "target_role": self.target_role,
            "results_count": self.results_count,
            "quota_used": self.quota_used,
            "status": self.status,
            "error_detail": self.error_detail,
        }


@dataclass
class RunReport:
    started_at: datetime
    dry_run: bool
    outcomes: list[FetchOutcome] = field(default_factory=list)
    rows_upserted: int = 0
    clusters_created: int = 0
    clusters_matched_exact: int = 0
    clusters_matched_fuzzy: int = 0

    @property
    def quota_spent(self) -> int:
        return sum(o.quota_used for o in self.outcomes)

    @property
    def failed(self) -> list[FetchOutcome]:
        return [o for o in self.outcomes if o.status == "error"]

    def render(self) -> str:
        lines = [
            "",
            "=" * 68,
            f"  postings ingest -- {'DRY RUN' if self.dry_run else 'LIVE'}",
            f"  started {self.started_at.isoformat(timespec='seconds')}",
            "=" * 68,
            f"  vendor calls      {len(self.outcomes)}",
            f"  quota spent       {self.quota_spent}",
            f"  listings returned {sum(o.results_count for o in self.outcomes)}",
            f"  rows upserted     {self.rows_upserted}",
            "",
            "  cross-source identity:",
            f"    exact  (ATS id from URL)  {self.clusters_matched_exact}",
            f"    fuzzy  (employer/title)   {self.clusters_matched_fuzzy}",
            f"    new clusters              {self.clusters_created}",
        ]
        errors = sum(len(o.normalization_errors) for o in self.outcomes)
        if errors:
            lines += [
                "",
                f"  !! {errors} listing(s) failed to normalize.",
                "     The field maps in normalize.py are unverified against live",
                "     responses -- a high count here means a wrong map, not bad data.",
            ]
            for o in self.outcomes:
                for e in o.normalization_errors[:2]:
                    lines.append(f"     - {e[:150]}")
        if self.failed:
            lines += ["", f"  !! {len(self.failed)} call(s) failed:"]
            for o in self.failed:
                lines.append(f"     - {o.source}/{o.target_role}: {o.error_detail}")
        lines.append("=" * 68)
        return "\n".join(lines)


def build_client(source: str):
    """Vendor client, constructed lazily so a missing credential for one vendor
    does not stop the other from running."""
    if source == "adzuna":
        from adzuna_client import AdzunaClient

        return AdzunaClient()
    if source == "jsearch":
        from jsearch_client import JSearchClient

        return JSearchClient()
    raise JobPostingConfigError(f"unknown source {source!r}")


def fetch_one(
    source: str,
    target_role: str,
    *,
    live: bool,
    page_size: int = DEFAULT_PAGE_SIZE,
    where: str = DEFAULT_WHERE,
    dump_shape: bool = False,
) -> FetchOutcome:
    """One vendor, one role, one call."""
    outcome = FetchOutcome(source=source, target_role=target_role)

    try:
        client = build_client(source)
    except JobPostingConfigError as exc:
        outcome.status = "error"
        outcome.error_detail = f"config: {exc}"
        return outcome

    try:
        if source == "adzuna":
            payload = client.search(
                what=target_role,
                where=where,
                distance=DEFAULT_DISTANCE_MILES,
                results_per_page=page_size,
                live=live,
            )
        else:
            payload = client.search(
                query=target_role,
                location=where,
                num_results=page_size,
                live=live,
            )
    except JobPostingRequestError as exc:
        outcome.status = "error"
        outcome.error_detail = f"request (transient={exc.transient}): {exc}"
        outcome.quota_used = 1  # a failed call still spends the call
        return outcome
    except TypeError as exc:
        # A client signature that does not match what this caller assumes is a
        # wiring bug, and it should be loud rather than logged as a vendor error.
        raise RuntimeError(f"{source} client signature mismatch: {exc}") from exc

    if payload is None:  # dry run -- the client printed the request
        return outcome

    outcome.quota_used = 1

    if dump_shape:
        print(describe_shape(payload, source))

    try:
        rows, errors = normalize_response(payload, source, target_role=target_role)
    except NormalizationError as exc:
        outcome.status = "error"
        outcome.error_detail = f"normalize: {exc}"
        return outcome

    outcome.rows = rows
    outcome.normalization_errors = errors
    outcome.results_count = len(rows)
    return outcome


def resolve_and_attach_identity(rows: list[dict], store: Any, report: RunReport) -> None:
    """Assign every row a posting_identity, per data/ats_fetcher/DEDUP.md.

    Exact before fuzzy, and never the other way round: an ATS id recovered
    from an apply URL is evidence, while an employer/title match is an
    inference, and an inference must not override evidence.
    """
    for row in rows:
        exact, fuzzy = identity_keys(row)
        cluster_id = None
        rule = None

        if exact is not None:
            cluster_id = store.find_cluster(exact)
            if cluster_id is not None:
                rule = "ats_url_id"
                report.clusters_matched_exact += 1

        if cluster_id is None and fuzzy is not None:
            cluster_id = store.find_cluster(fuzzy)
            if cluster_id is not None:
                rule = "fuzzy"
                report.clusters_matched_fuzzy += 1

        if cluster_id is None:
            cluster_id = store.create_cluster(
                keys=[k for k in (exact, fuzzy) if k],
                match_rule="seed",
            )
            report.clusters_created += 1
            rule = "seed"

        row["posting_identity"] = cluster_id
        row["_match_rule"] = rule


class DryRunStore:
    """Records what would happen. No network, no database."""

    def __init__(self) -> None:
        self.clusters: dict[str, str] = {}
        self.rows: list[dict] = []
        self.log_rows: list[dict] = []
        self._next = 0

    def find_cluster(self, key: str) -> str | None:
        return self.clusters.get(key)

    def create_cluster(self, keys: list[str], match_rule: str) -> str:
        self._next += 1
        cluster_id = f"dry-cluster-{self._next:05d}"
        for k in keys:
            self.clusters[k] = cluster_id
        return cluster_id

    def upsert_postings(self, rows: list[dict]) -> int:
        self.rows.extend(rows)
        return len(rows)

    def write_log(self, log_row: dict) -> None:
        self.log_rows.append(log_row)


class SupabaseStore:
    """Service-role writer.

    Uses SUPABASE_SECRET_KEY, matching scripts/import_students.py and
    scripts/fetch_smu_term_dates.py. That key bypasses RLS, which is the
    intended posture: job_postings is public-read and service-role-write, and
    posting_clusters denies everyone but the service role outright.
    """

    def __init__(self) -> None:
        from supabase import create_client

        url = os.environ.get("SUPABASE_URL", "").strip()
        secret = os.environ.get("SUPABASE_SECRET_KEY", "").strip()
        if not url or not secret:
            raise JobPostingConfigError(
                "SUPABASE_URL and SUPABASE_SECRET_KEY are both required to write."
            )
        self.client = create_client(url, secret)
        self._cluster_cache: dict[str, str] = {}

    def find_cluster(self, key: str) -> str | None:
        if key in self._cluster_cache:
            return self._cluster_cache[key]
        column = "url" if key.startswith("ats:") else None
        if column is None:
            return None
        # An exact key encodes ats:<board>:<id>; the stored row carries the URL
        # it was recovered from, so the lookup is over already-ingested rows.
        _, _, external_id = key.split(":", 2)
        found = (
            self.client.table(POSTINGS_TABLE)
            .select("posting_identity,url")
            .ilike("url", f"%{external_id}%")
            .not_.is_("posting_identity", "null")
            .limit(1)
            .execute()
            .data
        )
        if found:
            cluster_id = found[0]["posting_identity"]
            self._cluster_cache[key] = cluster_id
            return cluster_id
        return None

    def create_cluster(self, keys: list[str], match_rule: str) -> str:
        created = (
            self.client.table(CLUSTERS_TABLE)
            .insert({"match_rule": match_rule})
            .execute()
            .data
        )
        cluster_id = created[0]["id"]
        for k in keys:
            self._cluster_cache[k] = cluster_id
        return cluster_id

    def upsert_postings(self, rows: list[dict]) -> int:
        payload = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]
        for r in payload:
            r["fetched_at"] = datetime.now(timezone.utc).isoformat()
        result = (
            self.client.table(POSTINGS_TABLE)
            .upsert(payload, on_conflict=UPSERT_CONFLICT)
            .execute()
        )
        return len(result.data or [])

    def write_log(self, log_row: dict) -> None:
        self.client.table(FETCH_LOG_TABLE).insert(log_row).execute()


def run(
    *,
    sources: tuple[str, ...],
    roles: list[str],
    live: bool,
    write: bool,
    page_size: int,
    where: str,
    dump_shape: bool,
) -> RunReport:
    report = RunReport(started_at=datetime.now(timezone.utc), dry_run=not live)
    store: Any = SupabaseStore() if write else DryRunStore()

    for source in sources:
        for role in roles:
            outcome = fetch_one(
                source,
                role,
                live=live,
                page_size=page_size,
                where=where,
                dump_shape=dump_shape,
            )
            report.outcomes.append(outcome)

            if outcome.rows:
                resolve_and_attach_identity(outcome.rows, store, report)
                report.rows_upserted += store.upsert_postings(outcome.rows)

            if live:
                store.write_log(outcome.log_row())

    return report


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--source",
        action="append",
        choices=sorted({"adzuna", "jsearch"}),
        help=f"Vendor to fetch. Repeatable. Defaults to {list(NIGHTLY_SOURCES)} "
             f"-- JSearch is excluded from the nightly sweep on quota grounds.",
    )
    p.add_argument("--role", action="append", help="Target role. Repeatable. Defaults to all 14.")
    p.add_argument("--where", default=DEFAULT_WHERE)
    p.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE)
    p.add_argument(
        "--live",
        action="store_true",
        help="Actually call the vendors. Without this, prints the planned requests and exits.",
    )
    p.add_argument(
        "--write",
        action="store_true",
        help="Write to Supabase. Requires --live. The tables do not exist until the "
             "staged migration is applied, so this will fail until then.",
    )
    p.add_argument(
        "--dump-shape",
        action="store_true",
        help="Print what the vendor actually returned against what normalize.py expects. "
             "Use this to confirm the field maps with one deliberately-spent call.",
    )
    return p


def main() -> int:
    args = build_parser().parse_args()

    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")

    if args.write and not args.live:
        print("--write requires --live: refusing to write rows nothing fetched.", file=sys.stderr)
        return 2

    sources = tuple(args.source) if args.source else NIGHTLY_SOURCES
    roles = args.role if args.role else load_target_roles()

    if "jsearch" in sources and len(roles) > 3 and args.live:
        print(
            f"Refusing: {len(roles)} roles x jsearch would spend {len(roles)} of a "
            f"~200/month quota in one run, and the integration spec narrows JSearch "
            f"to LinkedIn-source confirmation. Pass --role explicitly to target it.",
            file=sys.stderr,
        )
        return 2

    report = run(
        sources=sources,
        roles=roles,
        live=args.live,
        write=args.write,
        page_size=args.page_size,
        where=args.where,
        dump_shape=args.dump_shape,
    )
    print(report.render())
    return 1 if report.failed and len(report.failed) == len(report.outcomes) else 0


if __name__ == "__main__":
    raise SystemExit(main())
