# GAP & SHIFT — Data Grounding
## Implementation spec

**Date:** 2026-08-09 · **Status:** Steps A–C built; D–E not started
**Verified against:** O\*NET 30.3 (`data/onet/onet_src/db_30_3_text/`), branch `feat/gap-shift-grounding`

---

## Why

**GAP** names `market_requirements` as its authoritative gap-scoring source and forbids scoring from `role_requirements`' skill lists ([campus_iq_prompt_GAP.md:47-58](../../CampusIQ_career/campus_iq_prompt_GAP.md#L47)). That source is backed by `data/reference/onet_soc_requirements.json` — 10 occupations, of which **2 of our 12 demo SOCs are populated**:

| SOC | Role | Today | After |
|---|---|---|---|
| 13-1071.00 | People Operations Intern | ✅ | ✅ |
| 13-1111.00 | Business Analyst Intern | ✅ | ✅ |
| 15-1252.00 | Software Engineering Intern | ❌ | ✅ |
| 17-2011.00 | Aerospace / Flight Systems Intern | ❌ | ✅ |
| 17-2061.00 | Computer Eng. / Embedded Systems Intern | ❌ | ✅ |
| 17-2141.00 | Mechanical Analysis Intern | ❌ | ✅ |
| 19-4021.00 | Lab Assistant | ❌ | ✅ |
| 19-4061.00 | Research Assistant | ❌ | ✅ |
| 21-1012.00 | Student Success Peer Mentor | ❌ | ✅ |
| 31-9092.00 | Pre-Health Clinical Volunteer | ❌ | ✅ |
| 13-2051.00 | Finance Intern | ⚠️ empty | agent + software |
| 13-1199.00 | Operations Intern | ❌ | agent |

**2 of 12 → 10 of 12 O\*NET-backed, 12 of 12 grounded.**

For the 10 uncovered SOCs today, GAP still emits confident must-have/nice-to-have splits and is asked to cite an O\*NET importance score ([line 101](../../CampusIQ_career/campus_iq_prompt_GAP.md#L101)) it was never given.

**SHIFT** sends the model nothing but student self-report. Its prompt reserves two injection points that nothing fills, so role-specific trend claims are model recall presented as market fact — e.g. from the cached Priya result: *"DFW aerospace employers increasingly mention Python ML skills in early-career postings."*

---

## Design

Four layers, each independently shippable. **Most of the work is in the loader, not the app.**

```
build_onet.py  ──emits──>  data/reference/onet_soc_requirements.json   (5.3 MB, 1,016 occupations)
                                            │
                        ┌───────────────────┴───────────────────┐
                        ▼                                       ▼
              market_data.get_market_requirements()   market_data.get_shift_signals()
                        │                                       │
                        ▼                                       ▼
                    GapRunner                              ShiftRunner
                        │                                       │
                        └──────── role_research_agent ──────────┘
                              (gap-fill only, not parallel)
```

---

## Step A — Loader emits the reference file

**File:** [data/onet/build_onet.py](../../data/onet/build_onet.py)

Add a reference-emit step writing `data/reference/onet_soc_requirements.json`, **replacing** the 10-role file at the path `market_data` already reads. Same top-level shape (`_meta` / `must_have_threshold` / `roles`), so `market_data`'s loader needs no structural change.

Two new source files to read (neither is currently extracted):

| Source | Filter | Feeds |
|---|---|---|
| `Task Statements.txt` | `Task Type == "Core"` | `core_tasks` — 893 occs, median 15 each |
| `Related Occupations.txt` | `Relatedness Tier == "Primary-Short"` | `related` — 923 occs, exactly 5 each |

Per-occupation entry. Element shape `{"name", "importance"}` is **unchanged** from today's file:

```json
"13-1111.00": {
  "title": "Management Analysts",
  "soc6": "13-1111",
  "job_zone": 4,
  "skills":      [{"name": "Critical Thinking", "importance": 78}],
  "knowledge":   [{"name": "English Language",  "importance": 93}],
  "abilities":   [{"name": "Oral Comprehension","importance": 78}],
  "hot_software": ["Microsoft Excel", "Tableau"],
  "core_tasks":  ["Analyze data gathered and develop solutions..."],
  "related":     [{"soc": "13-1081.00", "title": "Logisticians"}],
  "_data_status": "onet_full"
}
```

Inclusion rules — **preserve the existing ones** so nothing silently reinterprets:

- `skills` = `essential_skill` domain, full set (exactly 10 per occupation — matches today's `inclusion_rule`)
- `knowledge`, `abilities` = importance ≥ 50, sorted descending
- Importance rescaled `(native - 1) / 4 * 100`, as recorded in today's `_meta`
- `transferable_skill` (median 25/occ) is **not** merged into `skills` — add as a separate `transferable_skills` key at ≥ 50 if wanted later, so `skills` keeps its current meaning
- `hot_software` = distinct `product` where `hot_technology` is true

**Two fields get dropped:** `role_family` and `typical_education` are hand-curated, not derivable from O\*NET, and are never passed to the model — [market_data.py:153-163](../../CampusIQ_career/features/market_data.py#L153) forwards only title, job_zone, and the three requirement lists. Safe to drop; note it so nobody looks for them later.

**Size: 5.3 MB** as built — 3x my initial estimate, which omitted core task sentences (1.35 MB) and `indent=2` whitespace (1.65 MB). Compact JSON would be 3.6 MB, but indentation is kept so the annual refresh produces a reviewable line-level diff instead of one changed line. Note `out/` is gitignored, so this is the only O\*NET artifact that enters git history.

**All 1,016 occupations are emitted, not just the 894 rated ones.** An entry with empty lists and a `_data_status` of `partial_onet_profile` / `no_data` tells the caller more than a missing key: it separates "O\*NET has no ratings for this occupation" from "this SOC code isn't in the release", and those need different handling downstream (agent fallback vs. a bad mapping to fix).

**Supabase is deferred** (consistent with the dashboard plan's own Phase 1/Phase 2 split). Student data is already Postgres-backed via [supabase_client.py](../../CampusIQ_career/supabase_client.py), but reference data is file-backed and there's no reason to move static reference data behind a network call for this milestone. The loader's CSV output is unaffected, so a Supabase import remains available later.

### Two consequences found while building this

Both are caused by the catalog going from 10 occupations to 1,016. Neither is a defect in Step A, but both must be handled before this is shippable.

**1. `matched` no longer means anything — Step B must fix it.**
[market_data.py:146](../../CampusIQ_career/features/market_data.py#L146) sets `matched = bool(soc and entry)`. Every occupation now has an entry, so `matched` is `True` for all 14 demo roles — including Finance Intern and Operations Intern, which return empty requirement lists. The `notes` list, which previously warned "mapped to SOC but no O\*NET entry exists", is now empty.

Net effect is still strongly positive (2 → 12 roles with real data), but the two roles that regressed are exactly the two needing careful handling. `provenance` in Step B is the fix; `matched` should be re-derived from whether `skills` is non-empty, not from key existence.

**2. The agent's O\*NET corroboration check just became a real validator.**
[role_research_agent.py:59](../../CampusIQ_career/features/role_research_agent.py#L59) reads this same file and tags results `agent_onet_corroborated` when the SOC appears in it. Its own comment says the catalog is *"only 10 occupations — far too narrow to use for rejection."*

At 1,016 occupations that is no longer true. A SOC code absent from the catalog is now genuinely not a valid O\*NET-SOC 2019 code, so corroboration *could* be promoted to a rejection filter.

**Decided: it stays a soft tag.** Never used to reject. What changed is what it means — it no longer separates well-known occupations from obscure ones (every real occupation is in the catalog), it separates real SOC codes from invented ones. Narrower, but sharper, and it keeps the module's fail-open behaviour: an unreadable catalog corroborates nothing rather than rejecting everything.

**Test impact — resolved.** `tests/test_role_research_agent.py` encoded the 10-occupation assumption in its fixtures: `15-1252.00` and `17-2072.00` were chosen precisely because they were *absent* from the old catalog. Both are real occupations and now corroborate, which broke **20 tests** (not the ~8 a read-through suggested — the parametrized cache-miss cases share one fixture).

Verified by restoring the old catalog and re-running: 67 passed, 0 failed. So all 20 were caused by the catalog change alone, with nothing pre-existing underneath.

Fixed by flipping the fixtures to `agent_onet_corroborated` and adding `UNCORROBORATED_PAYLOAD` (`99-9999.00` — format-valid, and absent because the release stops at major group 55). That is now the only way to produce an uncorroborated result, which is exactly what the tag means post-change. One assertion that hardcoded the tag value was relaxed to assert a *legal* tag was assigned, since that test is about the write path, not the catalog.

---

## Step B — `market_data` gains provenance and software

**File:** [CampusIQ_career/features/market_data.py](../../CampusIQ_career/features/market_data.py)

`get_market_requirements()` keeps its signature and return shape. Additions to each `by_role` entry:

```python
"hot_software": [...],          # from the reference file
"provenance": "onet" | "agent" | "none",
```

`provenance` is the load-bearing new field — it's what lets the prompt distinguish "scored against real importance data" from "scored against web research." `market_data` emits only `"onet"` or `"none"`; it knows nothing about the research agent. `gap.py` upgrades `"none"` → `"agent"` for the roles it backfills in Step C.

`matched` is re-derived from non-empty `skills` rather than key existence, fixing the Step A regression. Finance Intern and Operations Intern now correctly report `matched: false` with an explicit note that their requirements must not be presented as O\*NET-scored.

Both existing invariants preserved: stdlib-only (verified — no first-party imports), and never raises into the runner (verified against a missing data file).

**`dfw_postings` is removed from the return shape.** It was always `None` and its comment promised "Phase 2: live Adzuna/JSearch." With the ATS fetcher closed, an always-`None` postings key is exactly the kind of dead placeholder Step D deletes from the SHIFT prompt — it invites the model to imply posting evidence that does not exist. Nothing read it.

**Payload check:** worst real student (3 roles) injects ~8.9 KB / ~2,300 tokens of `market_requirements`. Acceptable. But note `hot_software` can dominate — Ethan Brooks gets 192 product names against 99 actual rated items, and software carries no importance score to rank by. Step C should decide whether GAP *uses* the list or merely checks the student's tools against it; enumerating 192 tools is not a gap analysis.

---

## Step C — GAP: stop running the agent in parallel, start running it as fallback

**Files:** [gap.py](../../CampusIQ_career/features/gap.py), [campus_iq_prompt_GAP.md](../../CampusIQ_career/campus_iq_prompt_GAP.md)

Today [gap.py:142](../../CampusIQ_career/features/gap.py#L142) calls `role_research_agent.get_role_requirements(role)` for **every** role on every run, and the prompt then forbids using its skills output for scoring. The agent's research is paid for and discarded.

Change it to gap-fill:

```
for each target role:
    if reference file has ratings for its SOC  ->  use O*NET, skip the agent
    else                                       ->  run the agent, mark provenance="agent"
```

This resolves the contradiction without reversing the precedence rule — the rule assumed full O\*NET coverage, and Step A supplies it. It also drops the agent from 12 roles to 2, removing a research loop from almost every GAP run.

Prompt changes:

- Keep the existing precedence language. It now works as designed where `provenance == "onet"`.
- Add the fallback branch: when `provenance == "agent"`, score from the supplied requirements **and state plainly that O\*NET has no ratings for this occupation**. No invented importance scores.
- Replace the dead `[Script injects...]` block under **MARKET REQUIREMENTS** with a real reference to the context keys.
- The "cite its O\*NET importance score" instruction needs a `provenance == "onet"` guard.

**Finance Intern / Operations Intern:** both take the agent path. Finance Intern additionally has hot-software data even with no ratings, so it isn't fully degraded.

### Built — measured

Across the five demo students, **15 role-lookups now trigger 2 agent calls instead of 15.** Only one student (Jordan Reyes) triggers any, because only Finance Intern and Operations Intern lack O\*NET ratings. Each avoided call was a research loop of up to 3 tool rounds against a 90s budget, so this is the latency headroom that pays for SHIFT's trend research in Step D.

`provenance` is upgraded from `"none"` to `"agent"` in `gap.py`, not `market_data` — the latter is stdlib-only and knows nothing about the agent, so the upgrade happens in the one place both halves are in scope.

`role_requirements_for(roles, market=None)` takes the market block as an optional second argument. `build_student_context` passes the one it already built so the catalog isn't loaded twice; called directly (as tests do), it rebuilds. Gap-fill semantics apply either way — the behaviour does not depend on call style.

**Prompt:** the `hot_software` guidance is deliberately restrictive. With up to 192 unranked products per role, enumerating them isn't a gap analysis, so the prompt permits exactly one use — intersect against the student's own tools and name at most two or three genuinely missing ones. The dead `[Script injects...]` blocks are gone, including the DFW postings one, replaced by a note that no posting feed exists and copy implying posting counts is prohibited.

**Tests:** two existing tests asserted the agent runs for Business Analyst Intern (13-1111.00), which now has O\*NET coverage and correctly skips it. They were about merge semantics, not scheduling, so they were retargeted to Finance Intern — a role the agent genuinely runs for. Two new tests cover the actual new behaviour: that the agent is *not* called for O\*NET-rated roles, and that provenance is upgraded for agent-filled ones.

---

## Step D — SHIFT: ground all five output fields

**Files:** [shift.py](../../CampusIQ_career/features/shift.py), [campus_iq_prompt_SHIFT.md](../../CampusIQ_career/campus_iq_prompt_SHIFT.md), [role_research_agent.py](../../CampusIQ_career/features/role_research_agent.py)

`ShiftRunner.build_student_context` currently sends only student self-report. Add a `shift_signals` block from a new `market_data.get_shift_signals(target_roles)`:

| Output field | Grounding | Source |
|---|---|---|
| `adjacent_paths[]` | `related` (5 per occ, 11/12 SOCs) | local |
| `ai_fluency_guidance[]` | `hot_software` (median 7 per occ) | local |
| `durable_skills[]` | `core_tasks` + high-importance skills | local |
| `task_shifts[]` | trend research | Tavily |
| `role_evolution_summary` | trend research | Tavily |

**Trend research:** add a sibling entry point in `role_research_agent` — a `get_role_trends(role)` reusing the existing tool loop, round cap, time budget, cache, and never-raise contract, with its own prompt and schema. New prompt and schema, not new infrastructure.

Budget honestly: SHIFT gains a research loop per role. Step C removes one from GAP for 10 of 12 roles, so net per-student cost is roughly flat, and the per-role cache amortizes across the 5 demo students sharing 14 roles.

Prompt changes:

- Replace both `[Script injects...]` blocks with real references to `shift_signals`.
- **Cut posting-frequency claims outright.** The trend agent returns web sources, not a postings corpus, and the ATS work that would have supplied one is closed (see [data/onet/STATUS.md](../../data/onet/STATUS.md)). SHIFT may cite what the search found; it may not assert what share of DFW postings mention a skill. This is not a deferral — there is no pipeline coming, so the language goes rather than waits.
- Keep the "path-clarity, not threat-assessment" directive intact.

---

## Step E — Remove `{{placeholder}}` syntax

Both prompt files use `{{target_roles}}`, `{{expected_graduation}}`, `{{ai_anxiety_level}}` and document that they "are interpolated from the student JSON." No interpolation exists — [base.build_messages()](../../CampusIQ_career/features/base.py#L93) concatenates the template, the contract, and a student-context JSON block. There is no `.format`, template engine, or substitution anywhere in `CampusIQ_career`.

It works (the model reads the JSON), so this is cosmetic — but strip the braces and the header note rather than implementing a mechanism nothing needs. Affects FIT and PROFESSOR_COMMENTS too.

---

## Decisions made

Recorded so they don't get relitigated:

1. **SHIFT gets local O\*NET grounding *and* Tavily trend research** — all five fields grounded, accepting the per-role research loop.
2. **No-O\*NET roles use the agent with a provenance flag** — not nearest-neighbor. Borrowing a related occupation's importance scores would silently attribute another role's data, which is worst exactly where it matters most (Finance Intern).
3. **Reference data stays file-backed.** 1.7 MB, no migration, preserves `market_data`'s stdlib-only property. Supabase import stays available.
4. **The GAP precedence rule stands.** It assumed full O\*NET coverage; Step A supplies it. The agent moves from parallel source to gap-filler.
5. **`skills` keeps meaning `essential_skill`.** Transferable skills are additive later, not merged in.

---

## What this does not fix

- **122 of 1,016 occupations have no ratings data in O\*NET 30.3.** Operations Intern (13-1199.00) has neither ratings nor software. That's an O\*NET collection gap, not a bug; the agent path is the mitigation.
- **Free-text role resolution.** `resolve_soc()` is exact-match against 14 curated roles. Real students will type anything. `occupation_titles.csv` (57,543 titles) is built for this and unused — separate work, not needed for the demo personas.
- **Posting frequency claims.** Permanently out of scope. The ATS fetcher is closed, not parked — the only sources of posting frequency now would be a paid feed or a new build. Both GAP and SHIFT are designed here to never need one: O\*NET importance carries GAP, web-sourced trends carry SHIFT.
- **31.0 lands late August 2026.** Re-running the loader regenerates the reference file, so this design refreshes with it.

---

## Order

Step A unblocks everything. Steps C and D are independent once B lands.

```
A (loader) → B (market_data) → ┬→ C (GAP)
                               └→ D (SHIFT)
E (placeholders) — anytime, independent
```
