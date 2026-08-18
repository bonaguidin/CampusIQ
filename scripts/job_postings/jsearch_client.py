#!/usr/bin/env python3
"""Thin diagnostic wrapper around JSearch, built for the OpenWebNinja-direct
platform (NOT the RapidAPI marketplace listing of the same product).

SCRATCH / DIAGNOSTIC ONLY -- not wired into GradusIQ_career.

WHICH PLATFORM, AND WHY THIS WAS AMBIGUOUS
-------------------------------------------
.env carries a MISMATCHED credential pair: JSEARCH_BASE_URL is set to
"https://api.openwebninja.com" (OpenWebNinja-direct), but the only JSearch key
present is named JSEARCH_RAPIDAPI_KEY (RapidAPI-shaped name) -- not
JSEARCH_API_KEY, which is what the OpenWebNinja-direct pairing described in
the task would predict, and JSEARCH_RAPIDAPI_HOST (RapidAPI's other required
header) is unset. This client trusts JSEARCH_BASE_URL as the stronger signal
(it unambiguously names a host) and treats JSEARCH_RAPIDAPI_KEY's *value* as
the OpenWebNinja API key -- consistent with the key's own "ak_..." prefix,
which matches OpenWebNinja's key format, not a typical RapidAPI hash. Flagged
in the accompanying report as worth Deepak's confirmation: the variable name
itself is misleading regardless of which platform it's really for.

ENDPOINT PATH -- CORRECTED AFTER A LIVE 403
---------------------------------------------
The first version of this client defaulted to POST-hoc guesses
("/v1/job-search", cross-checked only against secondary sources) that 403'd
on the one live call made against them. DEFAULT_ENDPOINT_PATH below is now
"/jsearch/search-v2", confirmed directly from OpenWebNinja's own code samples
at openwebninja.com/api/jsearch/docs -- not a third-party reseller. The auth
header (x-api-key) and the query param name (query, not Adzuna's what) were
already correct in the prior version; only the path was wrong. Both
DEFAULT_ENDPOINT_PATH and DEFAULT_AUTH_HEADER stay overridable via
constructor args or CLI flags, and dry-run stays the default so a future
wrong guess still costs nothing.

CREDENTIALS: JSEARCH_BASE_URL + JSEARCH_RAPIDAPI_KEY, loaded via python-dotenv
from .env exactly once at CLI entry, matching adzuna_client.py's pattern. A
missing or blank credential raises JobPostingConfigError immediately, same
rationale as adzuna_client.py: no silent degrade.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from errors import JobPostingConfigError, JobPostingRequestError  # noqa: E402

# Confirmed against OpenWebNinja's own docs (openwebninja.com/api/jsearch/docs)
# after the prior guess ("/v1/job-search") 403'd. Override with --endpoint-path.
DEFAULT_ENDPOINT_PATH = "/jsearch/search-v2"

# Best-effort default; see the module docstring. Override with --auth-header.
DEFAULT_AUTH_HEADER = "x-api-key"

# Matches adzuna_client.py's DEFAULT_TIMEOUT_SECONDS and the ~15s explicit-
# timeout convention confirmed in role_research_agent.py's Tavily client.
DEFAULT_TIMEOUT_SECONDS = 15.0

_MASK = "***"

# The field(s) worth checking in a JSearch/OpenWebNinja result for source
# attribution (e.g. LinkedIn-via-Google-for-Jobs). Not confirmed against a
# real response -- both names show up across JSearch-family API variants, so
# the report step checks whichever is actually present rather than assuming.
CANDIDATE_SOURCE_FIELDS = ("job_publisher", "source", "via")


class JSearchClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        *,
        endpoint_path: str = DEFAULT_ENDPOINT_PATH,
        auth_header: str = DEFAULT_AUTH_HEADER,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        session: Any = requests,
    ) -> None:
        self.base_url = base_url if base_url is not None else os.getenv("JSEARCH_BASE_URL")
        self.api_key = api_key if api_key is not None else os.getenv("JSEARCH_RAPIDAPI_KEY")
        if not self.base_url or not self.base_url.strip():
            raise JobPostingConfigError("JSEARCH_BASE_URL is required for JSearch calls.")
        if not self.api_key or not self.api_key.strip():
            raise JobPostingConfigError("JSEARCH_RAPIDAPI_KEY is required for JSearch calls.")
        self.endpoint_path = endpoint_path
        self.auth_header = auth_header
        self.timeout = timeout
        self.session = session

    def build_request(
        self,
        *,
        query: str,
        location: str | None = None,
        num_results: int = 5,
        page: int = 1,
    ) -> tuple[str, dict[str, Any], dict[str, str]]:
        """Returns (url, params, headers) without sending anything."""
        url = f"{self.base_url.rstrip('/')}{self.endpoint_path}"
        params: dict[str, Any] = {"query": query, "page": page, "num_pages": 1}
        if location:
            params["location"] = location
        headers = {self.auth_header: self.api_key.strip()}
        return url, params, headers

    def masked_headers(self, headers: dict[str, str]) -> dict[str, str]:
        return {key: (_MASK if key == self.auth_header else value) for key, value in headers.items()}

    def search(
        self,
        *,
        query: str,
        location: str | None = None,
        num_results: int = 5,
        page: int = 1,
        live: bool = False,
    ) -> dict[str, Any] | None:
        """Dry-run by default: prints the request and returns None.

        Pass live=True to actually send it. num_results is accepted for
        symmetry with adzuna_client.search() but the request itself is
        capped by num_pages=1 -- trim the response client-side if the vendor
        doesn't support a smaller page size natively.
        """
        url, params, headers = self.build_request(
            query=query, location=location, num_results=num_results, page=page
        )
        if not live:
            print("[DRY RUN] JSearch request (not sent):")
            print(f"  GET {url}")
            print(f"  params: {params}")
            print(f"  headers: {self.masked_headers(headers)}")
            return None

        try:
            response = self.session.get(url, params=params, headers=headers, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            status = exc.response.status_code if exc.response is not None else None
            transient = isinstance(exc, (requests.ConnectionError, requests.Timeout)) or (
                status == 429 or (status is not None and 500 <= status < 600)
            )
            # Body included (not just str(exc)) so a 403/401 diagnosis doesn't
            # need a second live call to see what the vendor actually said --
            # the first 403 against this client discarded the body and left
            # only "Forbidden" to go on.
            body = exc.response.text if exc.response is not None else None
            raise JobPostingRequestError(
                f"JSearch request failed: {exc} | body={body!r}", transient=transient
            ) from exc

        return response.json()


def find_source_field(result_item: dict[str, Any]) -> tuple[str, Any] | None:
    """Returns (field_name, value) for the first populated source/publisher
    field found in a single result item, or None if none of
    CANDIDATE_SOURCE_FIELDS are present."""
    for field in CANDIDATE_SOURCE_FIELDS:
        if field in result_item and result_item[field]:
            return field, result_item[field]
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True, help="Search text, e.g. 'clinical volunteer'")
    parser.add_argument("--location", default="Dallas, TX")
    parser.add_argument("--num-results", type=int, default=5)
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--endpoint-path", default=DEFAULT_ENDPOINT_PATH)
    parser.add_argument("--auth-header", default=DEFAULT_AUTH_HEADER)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Actually send the request. Without this flag, only prints the request and exits.",
    )
    args = parser.parse_args()

    from dotenv import load_dotenv

    project_root = Path(__file__).resolve().parents[2]
    load_dotenv(project_root / ".env")

    try:
        client = JSearchClient(endpoint_path=args.endpoint_path, auth_header=args.auth_header)
    except JobPostingConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        result = client.search(
            query=args.query,
            location=args.location,
            num_results=args.num_results,
            page=args.page,
            live=args.live,
        )
    except JobPostingRequestError as exc:
        print(f"Request error (transient={exc.transient}): {exc}", file=sys.stderr)
        sys.exit(1)

    if result is not None:
        items = result.get("data") if isinstance(result, dict) else None
        items = items if isinstance(items, list) else []
        print(f"result count: {len(items)}")
        for item in items[: args.num_results]:
            title = item.get("job_title") or item.get("title")
            source = find_source_field(item)
            print(f"  - {title!r} source={source}")


if __name__ == "__main__":
    main()
