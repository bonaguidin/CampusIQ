# Job postings config

Hand-edited reference data for the postings ingest. Not code — these files are
meant to be read and corrected by people, and the ingest reads them at runtime
rather than hardcoding anything.

## Where these came from

Harvested 2026-08-19 from `ats-puller-draft`, a local-only skeleton repo that
was never under version control. That repo's Python is entirely
`raise NotImplementedError` stubs, but these three config files are real
hand-built work and were the only things in it at risk of being lost.

The skeleton implements `GradusIQ_ATS_Puller_Spec.md`; section references in
the comments inside each file point at that spec.

## Before anything reads these

Nothing in the repo parses them yet. Whoever wires that up has to do two
things together, not one:

1. Add `pyyaml` to `pyproject.toml`.
2. Run `uv lock` to regenerate `uv.lock`.

PyYAML is currently in the local venv only as a transitive dependency, so a
module that imports it will pass locally and fail on a fresh install. And the
CI workflow runs `uv sync --frozen`, which refuses a lockfile that does not
match `pyproject.toml` — so declaring the dependency without relocking breaks
the nightly run instead of fixing anything.

## The files

| File | What it is | Trust level |
|---|---|---|
| `role_families.yaml` | Title → role family rules, longest-phrase-first | **See the warning below** |
| `skill_aliases.yaml` | Canonical skill → surface forms | Starter set, unreviewed |
| `employers.example.yaml` | Shape template for the employer target list | Template only, no real data |

## WARNING: role_families.yaml targets a different taxonomy

The ten families in this file are general professional occupations. The
fourteen roles this product actually serves, in `data/role_requirements.json`,
are student and intern positions. They are not the same list and were not
built for the same purpose.

```
role_families.yaml          role_requirements.json
--------------------        ----------------------------------
financial_analyst      ~    Finance Intern
business_analyst       ~    Business Analyst Intern
software_engineer      ~    Software Engineering Intern
data_analyst                (no clear target role)
data_engineer               (no clear target role)
accountant                  (no clear target role)
it_support                  (no clear target role)
marketing                   (no clear target role)
human_resources        ~    People Operations Intern
supply_chain           ~    Operations Intern
                            Computer Engineering Intern    (no family)
                            Embedded Systems Intern        (no family)
                            Aerospace Engineering Intern   (no family)
                            Flight Systems Intern          (no family)
                            Mechanical Analysis Intern     (no family)
                            Lab Assistant                  (no family)
                            Pre-Health Clinical Volunteer  (no family)
                            Research Assistant             (no family)
                            Student Success Peer Mentor    (no family)
```

Roughly five map loosely and nine target roles have no family at all. Wiring
this file up as-is would leave most of the product's roles unmapped, and — the
worse failure — would map some titles into a plausible-looking wrong family.
The file's own comments name that asymmetry:

> Unmapped → shows up in the unmapped bin. Loud. Fixable.
> Mis-mapped → shows up as a plausible wrong percentage. Silent.

**Treat this as a worked example of the rule format, not as a usable mapping.**
It needs rewriting against the fourteen target roles before anything reads it.
The rules are deliberately cheap to change; that is the design, not a defect.

## skill_aliases.yaml is unreviewed

39 canonical skills. The file's header says the entries are a starter set and
marks the alias review as **Kasheia's**, distinct from the extraction
spot-check, which is Deepak's. Nothing has reviewed them yet.

Note this is a separate artifact from `skill_terms_review.csv` on the
`ats-fetcher` branch (8,725 candidate terms from O*NET, of which only 121 ever
fired against a real posting). Two different approaches to the same problem:
this one is small, curated and alias-based; that one is large, generated and
frequency-filtered. Someone should decide which survives rather than letting
both drift.

## dfw_employers_ats.csv — the real list, arrived 2026-08-19

44 hand-researched DFW employers plus one example row the loader skips.
Columns: priority, employer, sector, dfw_location, domain,
target_role_families, ats, slug, checked_date, notes.

**It does not make any employer fetchable.** The ATS fetcher needs `{ats,
slug}` per employer. This file has `ats` for **1 of 44** (Match Group, lever)
and `slug` for **0 of 44** — that column was never filled in. A slug is the
identifier in an employer's own careers URL and has to be looked up by hand,
per employer. Until that happens the table describes who to target, not who
can be reached.

`scripts/job_postings/load_employers.py` loads it and reports that gap in its
own output rather than leaving it to be discovered later. A test pins the
current state, so the first slug someone fills in will make that test fail —
which is the intended signal, not a regression.

Two other things to know:

- `notes` is mostly hypotheses — "Enterprise HCM likely — check for
  myworkdayjobs.com". That is the research still outstanding, written down. A
  guess about an employer's ATS is not a fact about it, and a slug pointing at
  the wrong company produces real postings attributed to the wrong employer.
- `target_role_families` uses the **mid-career taxonomy**, same as
  `role_families.yaml` and for the same reason. "Financial analyst; client
  service associate; risk/compliance" are not among the fourteen student roles
  in `data/role_requirements.json`. Loaded verbatim; remapping is the same
  outstanding decision described above.

PMG is not in this list, despite being one of the two employers actually
fetched in the 2026-08-05 run. Match Group is.

## employers.example.yaml

A shape template for the ats-puller-draft skeleton's own config format
(`{ats, slug, employer_name}` in YAML). Superseded by the CSV above for
content, kept because the skeleton's loader still refers to it.
