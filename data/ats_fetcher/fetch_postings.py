#!/usr/bin/env python3
"""
GradusIQ — ATS fetcher (stage 1 of the postings pipeline)

Pulls job postings from employers' own public ATS job boards and normalizes
them into one shape. Writes CSV. Does NOT touch Supabase, does not extract
skills, does not aggregate — those are later stages.

Run:  python fetch_postings.py --employers employers.json --out postings.csv
      python fetch_postings.py --employers employers.json --probe

All endpoints are public, unauthenticated, and are the same feeds that power
each employer's own careers page. No API keys.
"""

import argparse, csv, html, json, os, re, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone

UA = "GradusIQ-research/0.1 (labor market research; contact: [email])"
TIMEOUT = 30
PAUSE = 1.0          # seconds between requests to the same host — be polite

# ---------------------------------------------------------------- http

def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read())

TAG = re.compile(r"<[^>]+>")
WS = re.compile(r"[ \t]*\n[ \t\n]*")

def clean(raw):
    """ATS descriptions arrive as HTML, and Greenhouse double-escapes it.
    Unescape twice, strip tags, collapse whitespace."""
    if not raw:
        return ""
    t = html.unescape(html.unescape(raw))
    t = TAG.sub(" ", t)
    t = t.replace("\xa0", " ")
    t = re.sub(r"[ \t]{2,}", " ", t)
    return WS.sub("\n", t).strip()

# ---------------------------------------------------------------- adapters
# Each returns a list of dicts with the same keys. This is the whole point
# of the file: five different vendors, one shape downstream.

def fetch_greenhouse(slug):
    # One call returns every job with full content. No pagination.
    d = get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    out = []
    for j in d.get("jobs", []):
        out.append({
            "external_id": str(j.get("id", "")),
            "title": (j.get("title") or "").strip(),
            "location": ((j.get("location") or {}).get("name") or "").strip(),
            "url": j.get("absolute_url", ""),
            "posted_at": (j.get("first_published") or j.get("updated_at") or "")[:10],
            "description": clean(j.get("content", "")),
        })
    return out

def fetch_lever(slug):
    d = get_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    out = []
    for j in d:
        cats = j.get("categories") or {}
        # GOTCHA: Lever splits the posting across two fields. Requirements
        # usually live in `additionalPlain`. Taking only descriptionPlain
        # silently drops the part with the skills in it.
        body = "\n".join(filter(None, [
            j.get("descriptionPlain") or clean(j.get("description", "")),
            j.get("additionalPlain") or clean(j.get("additional", "")),
        ]))
        ts = j.get("createdAt")
        out.append({
            "external_id": str(j.get("id", "")),
            "title": (j.get("text") or "").strip(),   # NOT "title"
            "location": (cats.get("location") or "").strip(),
            "url": j.get("hostedUrl", ""),
            "posted_at": (datetime.fromtimestamp(ts / 1000, timezone.utc).date().isoformat()
                          if ts else ""),
            "description": body.strip(),
        })
    return out

def fetch_ashby(slug):
    d = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true")
    out = []
    for j in d.get("jobs", []):
        # Ashby is the only one that hands over clean plain text directly.
        body = j.get("descriptionPlain") or clean(j.get("descriptionHtml", ""))
        out.append({
            "external_id": str(j.get("id", "")),
            "title": (j.get("title") or "").strip(),
            "location": (j.get("location") or "").strip(),
            "url": j.get("jobUrl", ""),
            "posted_at": (j.get("publishedAt") or "")[:10],
            "description": body.strip(),
        })
    return out

def fetch_smartrecruiters(slug):
    # GOTCHA: the list endpoint has NO description. Each posting needs a
    # second call. That's N+1 requests — slowest adapter by far.
    out, offset = [], 0
    while True:
        d = get_json(f"https://api.smartrecruiters.com/v1/companies/{slug}"
                     f"/postings?limit=100&offset={offset}")
        items = d.get("content", [])
        if not items:
            break
        for j in items:
            jid = j.get("id")
            body = ""
            try:
                time.sleep(PAUSE)
                det = get_json(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings/{jid}")
                secs = (det.get("jobAd") or {}).get("sections") or {}
                body = "\n".join(clean((secs.get(k) or {}).get("text", ""))
                                 for k in ("jobDescription", "qualifications", "additionalInformation"))
            except Exception as e:
                print(f"      detail fetch failed for {jid}: {e}", file=sys.stderr)
            loc = j.get("location") or {}
            out.append({
                "external_id": str(jid),
                "title": (j.get("name") or "").strip(),   # NOT "title"
                "location": ", ".join(filter(None, [loc.get("city"), loc.get("region")])),
                "url": j.get("ref", ""),
                "posted_at": (j.get("releasedDate") or "")[:10],
                "description": body.strip(),
            })
        offset += len(items)
        if offset >= d.get("totalFound", 0):
            break
        time.sleep(PAUSE)
    return out

ADAPTERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
    "smartrecruiters": fetch_smartrecruiters,
}

# ---------------------------------------------------------------- run

FIELDS = ["employer", "ats", "external_id", "title", "location",
          "url", "posted_at", "description", "pulled_at"]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--employers", default="employers.json")
    ap.add_argument("--out", default="postings.csv")
    ap.add_argument("--probe", action="store_true",
                    help="check every board returns postings, write nothing")
    args = ap.parse_args()

    if not os.path.exists(args.employers):
        sys.exit(f"No employer list at {args.employers}")
    employers = json.load(open(args.employers))
    today = datetime.now(timezone.utc).date().isoformat()

    rows, log = [], []
    for e in employers:
        name, ats, slug = e["name"], e["ats"].lower(), e["slug"]
        if ats not in ADAPTERS:
            print(f"  {name:<28} SKIP unsupported ats '{ats}'"); continue
        try:
            got = ADAPTERS[ats](slug)
            print(f"  {name:<28} {ats:<16} {len(got):>5} postings")
            log.append((name, ats, len(got), "ok"))
            if not args.probe:
                for g in got:
                    rows.append([name, ats, g["external_id"], g["title"],
                                 g["location"], g["url"], g["posted_at"],
                                 g["description"], today])
        except urllib.error.HTTPError as ex:
            code = ex.code
            hint = ("board not found — wrong slug, or they changed ATS"
                    if code == 404 else "rate limited, slow down" if code == 429 else "")
            print(f"  {name:<28} {ats:<16} HTTP {code}  {hint}")
            log.append((name, ats, 0, f"http_{code}"))
        except Exception as ex:
            print(f"  {name:<28} {ats:<16} ERROR {type(ex).__name__}: {ex}")
            log.append((name, ats, 0, "error"))
        time.sleep(PAUSE)

    # Per-employer counts. This is the drift monitor: an employer switching
    # ATS shows up as a zero here, not as silently shifted denominators later.
    with open("pull_log.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["employer", "ats", "count", "status", "pulled_at"])
        for r in log:
            w.writerow(list(r) + [today])

    ok = sum(1 for r in log if r[3] == "ok")
    print(f"\n  boards ok: {ok}/{len(log)}   postings: {sum(r[2] for r in log):,}")

    if args.probe:
        print("  probe only — nothing written")
        return

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(FIELDS)
        w.writerows(rows)
    mb = os.path.getsize(args.out) / 1024 / 1024
    print(f"  wrote {args.out}  ({len(rows):,} rows, {mb:.1f} MB)")
    print("\n  NOTE: this CSV holds full description text and is a scratch file.")
    print("  Stage 2 extracts skills from it; the text is not what gets stored.")

if __name__ == "__main__":
    main()
