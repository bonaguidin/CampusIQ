# Status

## ATS postings fetcher — CLOSED (2026-08-09)

Not parked. Closed.

The fetcher (`data/ats_fetcher/`) was built to supply a postings corpus so the skill
matcher could make frequency claims ("X% of DFW postings ask for SQL"). That was
already out of pilot scope, and NLx access — the last plausible path to a real corpus —
isn't expected to get us there either. PR #20 closed, not merged.

**Nothing downstream is waiting on this.** GAP scores against O\*NET importance
(see `docs/plans/gap-shift-data-grounding.md`); SHIFT grounds trend claims in web
research. Both are designed to never need a postings corpus. Any copy that still
implies posting frequencies is a bug, not a placeholder.

Re-open only if a real corpus becomes available. If that happens, start here.

### Where the work survives

| Artifact | Location | Notes |
|---|---|---|
| Fetcher + matcher code | local branch `ats-fetcher` @ `cb23f45` | `fetch_postings.py`, `build_skill_terms.py`, `employers.json`, `skill_terms.csv` |
| `skill_terms_review.csv` | local branch `ats-fetcher` | The curated review decisions — the reusable part. Worth keeping regardless. |
| `postings.csv`, `pull_log.csv` | untracked working tree only | The pulled corpus. Gitignored, so in no history anywhere. |

**Local only — deliberate.** `origin/ats-fetcher` was deleted and the branch is not being
re-pushed. The code lives on one local branch, the corpus only as untracked files on one
machine, and neither is backed up. Accepted risk: the work is closed, and a re-open would
mean re-pulling a fresh corpus anyway — the part actually worth keeping is
`skill_terms_review.csv`, and it is small enough to copy by hand if it ever matters.

## O\*NET load

Built and verified — see `README.md`. Wiring it into GAP and SHIFT is specced in
`docs/plans/gap-shift-data-grounding.md`.
