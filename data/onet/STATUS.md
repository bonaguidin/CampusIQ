# Status

The skill vocabulary / matcher work is parked pending a real postings corpus.

The ATS postings fetcher (`data/ats_fetcher/` on the `ats-fetcher` branch) was built to
supply that corpus, but frequency claims are out of pilot scope, so it's deferred —
GAP will use O*NET importance scores instead. See PR #20 (closed, not merged) for
context. Revisiting if NLx access lands.

`skill_terms_review.csv` (on the `ats-fetcher` branch) should be preserved even
though this work is paused — the review decisions in it are reusable once a real
postings corpus is available.
