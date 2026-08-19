# Cross-source identity — build spec

**What this is:** the rule for deciding that a posting arriving from an ATS feed and a
posting arriving from a job search API are *the same job*. Companion to `README.md` §3.

**Why it is separate:** the README's dedup key, `(source_ats, external_id)`, is correct
and stays. It answers "has this source sent me this posting before." It cannot answer
"have I already counted this job under a different source," because each source mints
its own id. Adding two job search APIs alongside the ATS feeds makes that second
question load-bearing for the first time.

---

## 1. The failure this prevents

Job search APIs syndicate ATS listings. The same Match Group role will plausibly arrive
three times on one nightly run: once from Lever directly, once from each API. Three
records, three different `external_id`s, no existing rule connecting them.

Every one of those is a separate row, so it is a separate vote in skill frequency
counting. A role syndicated widely outvotes a role that is only on the employer's own
board — and the ranking that comes out reflects *syndication reach*, not the DFW labor
market. This is the same class of silent inflation the README flags for `external_id`,
one level up.

It also gets worse with time rather than better: retroactively splitting counts across a
populated table means re-deriving identity for every row ever ingested. **Decide before
the nightly job starts accumulating.**

---

## 2. Two layers, not one

| Layer | Key | Answers | Status |
|---|---|---|---|
| Record | `(source, external_id)` | Did this source re-send this posting? | Unchanged from README §3 |
| Cluster | `posting_identity` | Is this the same job as one I already have? | New |

A record belongs to exactly one cluster. A cluster holds one or more records. Upsert
still happens at the record layer — the cluster layer sits above it and is derived.

**Counting iterates clusters, never records.** That is the entire point of the layer.

---

## 3. Assigning a cluster

Resolve in order. First match wins.

### 3.1 Recovered ATS id — the primary path

Job search APIs carry a link back to the employer's ATS posting, and **ATS URLs embed
the job id in the path.** From the corpus already pulled:

```
https://job-boards.greenhouse.io/pmg/jobs/8496729002
                                           ^^^^^^^^^^ external_id
```

So: parse the apply URL, identify the ATS by host, extract the id by that ATS's path
shape, and cluster on the recovered `(ats, id)`. This is an **exact** match against a
record already ingested from that ATS — no fuzzy matching, no threshold, no false
positives. It should catch the large majority of syndicated duplicates, which is most
of the problem.

Normalize before parsing: lowercase host, strip query string and fragment (tracking
params are how syndicators mark their referrals), strip trailing slash. Keep the raw
URL as well — it is the audit trail for "why did these two get merged."

Write one extractor per ATS host, same shape as the existing per-ATS fetch adapters.
An unrecognized host falls through to 3.2 rather than erroring.

### 3.2 Fuzzy identity — the fallback

For records where no ATS URL is recoverable (API-native postings, employers not on a
supported ATS), cluster on:

```
(normalized_employer, normalized_title, dfw_bucket)
```

- `normalized_employer` — casefold, strip legal suffixes (Inc, LLC, Corp, Ltd), strip
  punctuation. Maintain an explicit alias map for the known employer list rather than
  relying on string distance; the employer set is small and curated.
- `normalized_title` — casefold; strip the seniority markers already parsed into the
  `seniority` field, so "Sr. Data Analyst" and "Data Analyst" collapse; strip req
  numbers and parenthetical location suffixes.
- `dfw_bucket` — the `is_dfw` boolean, not the raw location string. Syndicators rewrite
  location text freely ("Dallas, TX" / "Dallas-Fort Worth" / "Dallas Metroplex"), so
  matching on raw text splits clusters that should merge.

Scope to postings seen within a rolling window (start at 30 days) so a genuinely
reposted role next quarter is not merged into last quarter's.

**This path will make mistakes**, unlike 3.1. Two real openings for the same title at
the same employer do exist. Accept the merge — undercounting one duplicate role is a
much smaller distortion than counting a syndicated role three times, and it fails in
the conservative direction.

### 3.3 No match

New cluster, seeded by this record.

---

## 4. Canonical record within a cluster

**The ATS record always wins.** It is the employer's own feed: most accurate title, real
posting date, no syndicator rewriting. Where no ATS record exists in the cluster, rank
the APIs in a fixed configured order — arbitrary but stable, so output does not change
based on which source happened to answer first on a given night.

Non-canonical records contribute **only fields the canonical record lacks**. The concrete
win is salary: the README notes Lever and Ashby carry it and others do not, so an API
record can fill `salary_min`/`salary_max` on a Greenhouse-canonical posting. It must not
overwrite a value the ATS already provided.

---

## 5. Clusters are revisable

Cluster assignment happens at ingest, not query time — counting reads must not pay for
identity resolution.

But it cannot be write-once. A job search API may deliver a posting on Monday, and the
employer's own ATS feed may first surface it on Tuesday. Monday's record sits in a fuzzy
3.2 cluster; Tuesday's arrival is the exact 3.1 evidence that it belongs elsewhere.
**Merging two clusters must be a supported operation**, which means `posting_identity`
is a mutable foreign key, not a hash baked into the row.

Log every merge with the rule that triggered it. When a count looks wrong, the question
will be "what got merged into what," and that has to be answerable from a table rather
than by re-running the pipeline.

---

## 6. Open

- **Which two APIs.** Endpoint shapes decide how much of §3.1 is reachable — specifically
  whether each carries a real ATS apply URL or only its own redirect. A source that
  hides the destination behind a tracking redirect drops to §3.2 for everything, which
  materially weakens dedup. Worth checking before committing to a provider.
- **Whether an API-only posting counts at all.** A posting that never appears on any
  employer ATS board may be a staffing-agency relist rather than a distinct opening.
  Leaning toward ingesting it and tagging the source, so the decision stays reversible
  from stored data.
- **Whether §3.2's 30-day window is right.** No evidence either way yet; revisit once a
  real corpus exists.
