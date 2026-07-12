# Demo Cache — Runbook

**What this folder is:** the pre-generated fallback reports the demo falls back to if live generation fails (OpenRouter slow/down at showcase time).

**Owner:** Person C (Output + Demo Readiness)

---

## Folder layout

```
demo_cache/
├── source_md/          representative report markdown (the INPUTS)
│   ├── ethan_brooks_combined.md
│   ├── ethan_brooks_FIT.md
│   ├── ethan_brooks_GAP.md
│   └── ethan_brooks_SHIFT.md
├── out/                the generated cache — PDF + DOCX (COMMIT THESE)
├── generate_cache.py   regenerates out/ from source_md/
└── CACHE_RUNBOOK.md    this file
```

The files in `out/` **are** the fallback. They're what gets served if the live pipeline can't run.

---

## Regenerate the cache

From this folder:

```
python generate_cache.py
```

Reads every source in `source_md/`, writes PDF + DOCX to `out/`. Requires `pandoc`, `pypandoc`, and `weasyprint` installed (see export.py notes).

---

## IMPORTANT — real vs representative content

The current `source_md/` files are **representative**, not live model output. This is deliberate: the pipeline that produces real reports (data layer → agents → Report Generator) isn't built yet, so a genuinely-real cache can't be generated today.

**When the real pipeline works, upgrade the cache like this:**

1. Run the real pipeline against Ethan's profile → get real report output.
2. If the output is markdown (Rep's expected format), drop it straight into `source_md/`, replacing the representative file.
3. If the output is JSON (raw agent format, pre-Rep), it needs to pass through the Report Generator first to become markdown. Cache the **post-Rep markdown**, not raw agent JSON.
4. Re-run `python generate_cache.py`.
5. Commit `out/`.

Filenames and structure stay identical — nothing downstream changes. Swapping representative content for real content is a re-run, not a rebuild.

---

## Scope note — academic features

Current cache covers **combined + the career three (FIT/GAP/SHIFT).** The four academic per-feature reports (professor comments, exam gap, study guide, course rec) aren't cached yet because their runners aren't built. When they exist, add their source markdown to `source_md/` and their entries to the `FEATURE_MAP` in `generate_cache.py` (placeholders already stubbed in the file).

---

## The other half — fallback WIRING (not in this folder)

This folder produces the cached *files*. Something still has to *detect live failure and serve them.* That logic lives in the trigger/orchestrator layer, not here:

```
try:
    result = run_live_pipeline(student)      # live OpenRouter call
except (Timeout, APIError, EmptyResult):
    result = load_cached_report(student)     # read from out/
display(result)
```

**This wiring is a seam with whoever owns the trigger layer.** Person C supplies the cached files; the trigger layer needs to catch failures and reach for them. Flag this so it doesn't fall between lanes.
