# ATS Postings Puller — Build Spec

**What this is:** a nightly Python job that pulls job postings from employers' own ATS boards, extracts a fixed field set, counts skill frequency per role family, and writes to Supabase. No model calls anywhere in this path.

**Status:** decided. The items below are settled decisions, not options. Where something is genuinely open it is marked OPEN and left to your judgment.

**Who reviews this:** Deepak owns integration. This is a working draft for his review, not a merge-ready component.

---

## 1. Why no model in this path

Counting is the one thing a `for` loop does better than an LLM. Pure string processing means: no cost per posting, no latency, no API key, and identical output for identical input — so when a number looks wrong it can be traced to a line rather than to a prompt.

Models still do all the reasoning students see (FIT, GAP, SHIFT, Comment Analyzer). They read the counted table. They do not produce it.

**Constraint: no LLM call, no model API key, and no inference dependency anywhere in this script.**

---

## 2. Sources

Public, zero-auth JSON endpoints published by each ATS. This is not scraping — it is the same feed that powers the employer's own careers page.

| ATS | Endpoint | Notes |
|---|---|---|
| Greenhouse | `boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` | One call returns everything, no pagination even on large boards. `content` comes back as HTML-escaped HTML — needs an unescape pass before parsing. |
| Lever | `api.lever.co/v0/postings/{company}?mode=json` | Sometimes carries salary |
| Ashby | `api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true` | Usually carries salary |
| SmartRecruiters | `api.smartrecruiters.com/v1/companies/{company}/postings` | Paginated, limit/offset |
| Recruitee | `{company}.recruitee.com/api/offers/` | Scoped, not yet implemented — see status note below |

**Status: four platforms implemented** (Greenhouse, Lever, Ashby, SmartRecruiters), each confirmed against a real employer board. Recruitee is scoped in this table but has no adapter — no Recruitee-boarded employer exists in the current target list to build and verify one against. Add `fetch_recruitee` once one does.

Five response shapes scoped, four implemented. **The work is normalization, not fetching.** Normalize each into one internal posting object before anything else touches it.

Rate limits are undocumented. Be polite: sequential requests, a small delay between employers, retry with backoff, and never hammer on failure.

**Employer slug list is supplied separately** (Noah's work — DFW employer targets). Read it from a config file, one row per employer: `{ats, slug, employer_name}`. Do not hardcode.

---

## 3. Field set — what gets extracted per posting

The storage rule: **pull the description, read it, keep the findings, discard the prose.** Anything not extracted on the nightly run is gone — postings come down and cannot be re-pulled.

That makes this field set the ceiling on everything GAP can ever say. Bytes are not the constraint; forgetting to extract is.

### Structural — straight off the ATS JSON

| Field | Notes |
|---|---|
| `source_ats` | greenhouse / lever / ashby / smartrecruiters / recruitee |
| `external_id` | The ATS's own job ID. **Dedup key — load-bearing.** Without it the same job recounts every night and percentages inflate silently. Upsert on `(source_ats, external_id)`. |
| `employer` | Company name |
| `title_raw` | Posting title exactly as written. Needed for hand-verification and for the unmapped bin. |
| `location_raw` | As given by the ATS |
| `url` | Link to the live posting. Makes spot-checking possible — "go look at this one." |
| `date_posted` | Employer's posting date where available |
| `date_pulled` | This run's date |

> **Cross-source note.** `(source_ats, external_id)` dedups *within* a source only. Once job search APIs run alongside these feeds, the same job arrives under several ids and needs a second identity layer above this key — see `DEDUP.md`.

### Derived — computed at ingest

| Field | Notes |
|---|---|
| `role_family` | One of the 14 student role families, or **NULL**. See §5. |
| `is_dfw` | Boolean, derived from `location_raw`. **Load-bearing.** Handle remote/hybrid/multi-location explicitly rather than defaulting. |
| `seniority` | `entry` / `mid` / `senior` / `unknown`, from title keywords (senior, sr., lead, principal, staff, manager, director, II, III). Tag only — see §6. |
| `matched_skills` | Array of canonical skill names found in the description. **The actual payload.** See §4. |
| `salary_min`, `salary_max` | Where the ATS carries it (Lever, Ashby). Null otherwise. Free when present; unrecoverable if skipped. |

### Discarded

Full description prose, **with one hedge:** retain raw description text on a rolling 7-day window so extracted-vs-source can be diffed during verification, then delete. This is a `DELETE` statement in the nightly job — Supabase has no built-in row expiry.

---

## 4. Skill matching

**Rule: word-boundary matching against a canonical → alias table, longest alias first. Never naive substring search.**

The table is bounded, not open-ended: build aliases **only** for skills O*NET already rates as important for the 14 student role families (§5). O*NET's importance scores are the skill set; the alias table only teaches the matcher to find those skills in prose. That is roughly 60–120 skills, reviewable by hand.

### Table shape

| canonical | aliases |
|---|---|
| SQL | SQL, Structured Query Language, T-SQL, PL/SQL |
| Power BI | Power BI, PowerBI, Power-BI |
| Excel | Excel, Microsoft Excel, MS Excel |
| JavaScript | JavaScript, JS |
| Salesforce | Salesforce, SFDC |

Store as a config file (JSON or YAML), not inline in code. It will be edited by a non-engineer.

### Four edge cases the matcher must survive

1. **Substring false positives.** "Excel" must not fire inside "Excellent communication skills." Word boundaries handle this.
2. **Nested aliases.** Word boundaries do *not* save Java from JavaScript — JavaScript has its own boundaries. **Match longest alias first and consume the matched span** so JavaScript is claimed before Java gets a turn.
3. **Symbol skills.** `C++` and `C#` break normal `\b` regex, because `+` and `#` are themselves word boundaries. Match these as escaped literal strings with custom boundary logic.
4. **Single-letter skills.** "R", "C", "Go", "D". Bare "R" matches nearly everything. **Require an adjacent qualifier** ("R programming", "in R", "using Go") or accept an undercount. Do not attempt to match naked single letters — the false positives are worse than the misses.

### Deferred to post-pilot

Skills that need *reading* rather than *finding* — "comfortable presenting to senior stakeholders", "applies professional skepticism". String matching cannot catch these. Until then, O*NET's occupation-level ratings cover the soft-skill side. Do not build for this now.

---

## 5. Role family mapping — OPEN, your call on approach

**Taxonomy note (added after this doc was written):** the illustrative titles and
implied ~10-family taxonomy below predate a rewrite of the target role families.
The current 14 student role families live in
`data/job_postings/role_families.yaml` (branch `feat/postings-grounding`, merged
to `dev`) — the same keys `data/role_requirements.json` and FIT/GAP already use.
When this mapping actually gets built for ats-fetcher, scope it against that
file's 14 families and its matching approach (longest-phrase-first,
`exclude_phrases`, NULL-not-drop), not the ~10-family framing implied here. That
file's own header also documents why a mapped-title hit rate as low as 1-2% on
employer-direct boards is expected, not a bug — worth reading before assuming
these rules are broken.

`role_family` is the join key for `skill_frequency`, so a title in the wrong bucket contaminates that family's percentages.

Employers do not write titles in our taxonomy. Real examples (illustrative only — from the pre-rewrite taxonomy; see the note above):

- "Financial Analyst I"
- "Sr. Financial Analyst, FP&A"
- "Analyst, Corporate Finance"
- "Business Analyst — Revenue Operations"
- "Associate, Financial Planning"

**Approach is yours to reason about.** Suggested starting point: keyword rules per family, longest-phrase-first. The rules are cheap to change — wrong rules get rewritten and tonight's pull re-run.

### The one hard constraint

**Titles that match no family are still written to the row, with `role_family` set to NULL. Never drop a posting for failing to map.**

Why this is non-negotiable:

- The unmapped bin is the list of real DFW titles the taxonomy is missing. It is data that can only be collected by collecting it — drop it and the gap stays invisible.
- Reclassifying later is a SQL `UPDATE`, not a re-pull. Deciding "Revenue Operations Analyst" belongs in business analyst backfills existing rows and the history comes with it.
- If 40% of the corpus lands unmapped, that needs to be visible in a table, not silently absorbed into a number that looks fine.

Log a per-run count of unmapped titles.

---

## 6. Seniority — tag, do not filter

Seniority is not cut and dry. "Analyst II" is entry at one employer and not at another. Filtering at ingest would bake a judgment call into data that cannot be undone.

**So: tag every posting, keep everything, filter at query time.**

**Downstream consequence that must be written into GAP's read path:** since senior roles are in the table, GAP has to apply the entry-level filter itself. Reading `skill_frequency` unfiltered means the percentages include senior roles and the number stops meaning "entry-level readiness." This is obvious now and invisible in three months.

---

## 7. Tables

### `postings` — one row per job

Fields per §3. Upsert on `(source_ats, external_id)` so re-pulls update rather than duplicate.

### `skill_frequency` — computed after each run

| Column | Notes |
|---|---|
| `role_family` | |
| `skill` | Canonical name |
| `mention_count` | Postings in this family containing this skill |
| `total_postings` | Postings in this family in the window |
| `window_start`, `window_end` | The date window counted |
| `computed_at` | |

GAP reads `skill_frequency`, never `postings` directly.

---

## 8. Retention

| Data | Policy | Why |
|---|---|---|
| Raw description text | Delete after 7 days | Verification window only. Storage pressure. |
| Extracted `postings` rows | Keep. Optional floor at 12–18 months. | Closed postings are history, not noise. "SQL climbed from 40% to 62% since fall" only exists if the past was kept — and that is SHIFT's thesis. Extracted-fields-only is a few hundred bytes per posting; a year of nightly pulls stays under 20 MB against a 500 MB free tier. |
| `skill_frequency` | Keep all | Trend data |

Staleness is a **query** problem, not a storage problem. Date-window the reads (last 30 days for current claims) and old rows cannot contaminate anything.

Supabase has no TTL. Deletion is an explicit `DELETE` in the nightly job.

---

## 9. Fallback rule — hard

**Fewer than ~30 postings for a role family in the window, GAP does not state a percentage.** It cites O*NET importance scores instead, with explicit disclosure to the student.

The difference in output:

- Sufficient corpus: "SQL appears in 62% of entry-level DFW postings for this role."
- Below floor: "SQL is rated high-importance for this occupation." (O*NET)

This makes the postings source a **quality tier, not a dependency.** Nothing here blocks a pilot; it determines how strong GAP's claims are allowed to be. Surface the per-family posting count so this rule can be evaluated at read time.

---

## 10. Where it runs — OPEN

GitHub Actions cron or Supabase pg_cron. Either is fine. One consideration: Supabase free projects pause after 7 days without database activity, so the nightly job also keeps the project alive — which means the cron cannot lapse over a break.

---

## 11. Build against scratch first

Do not point this at the production Supabase project. Use a local JSON fixture set or a throwaway Supabase project until the table shapes are confirmed with Deepak.

---

## 12. Verification before any number is trusted

Two separate checks, not to be conflated:

- **Alias table review (Kash).** Is "Salesforce Admin" a skill or a job title? Domain judgment.
- **Extraction spot-check (Deepak).** Hand-verify ~30 postings against what the script extracted. Roughly an hour, and it is the difference between a number worth showing a school and a number that hopes nobody checks.

Make this easy: a small script that dumps N random postings side by side — `title_raw`, `role_family`, `seniority`, `matched_skills`, `url` — for eyeball comparison against the live posting.

---

## Summary of locked decisions

- Zero model calls in this path
- Field set per §3, including `is_dfw` and `seniority`
- Longest-match-first alias matching, bounded to O*NET skills for the 14 student role families (see the taxonomy note in §5)
- Keep and tag seniority; filter at read time, not ingest
- Unmapped titles preserved with NULL `role_family` — never dropped
- Raw text deleted at 7 days; extracted rows kept
- Sub-30-posting families fall back to O*NET importance scores
