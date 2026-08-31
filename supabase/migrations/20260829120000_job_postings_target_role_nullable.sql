-- STAGED -- not yet applied to Supabase. Same posture as its two siblings
-- (20260817210000_job_postings_reference_draft.sql,
-- 20260822170000_job_postings_grounding_amendments.sql): review, then apply
-- with a deliberate `supabase migration up`, not as a side effect of a merge.
--
-- WHAT THIS DOES
--
-- Relaxes job_postings.target_role from `text not null` to nullable.
--
-- WHY
--
-- The Workday adapter (scripts/job_postings/workday.py, wired into the ingest
-- in this same change) fetches an employer's WHOLE board in one pass --
-- `searchText: ""`, no per-role server-side filter -- exactly like the ATS
-- fetchers and unlike Adzuna/JSearch, which query one target_role at a time.
-- A whole-board row has no target_role to record. NULL says that honestly.
--
-- This is the same move already made one migration earlier on the sibling
-- column: 20260822170000 relaxed job_posting_fetch_log.target_role to nullable
-- with the note "an ATS fetch loops employers, not target roles". Same cause,
-- same fix, now on job_postings itself. raw_payload was relaxed the same way
-- in that migration -- a bare DROP NOT NULL, no replacement CHECK -- and this
-- follows that precedent rather than inventing a sentinel role string or a
-- has_subject-style constraint. job_postings has no `employer` column to OR
-- against (only a nullable `company`), so there is no clean second subject
-- for such a CHECK, and a sentinel would poison both the anticipated
-- (source, target_role, source_job_id) uniqueness semantics and the
-- (target_role, fetched_at desc) "postings for this role" index every future
-- reader would then have to special-case.
--
-- SAFETY
--
-- Relaxing NOT NULL cannot violate any existing row. Nothing reads
-- job_postings.target_role today: no application code touches the table
-- (GradusIQ_career/features/market_data.py states outright that posting data
-- is not part of FIT/SHIFT/GAP grounding), no view/function/RPC references the
-- column, and the only index on it (job_postings_target_role_fetched_idx) is a
-- plain btree that sorts NULLs last without complaint. The eventual grounding
-- read path counts posting_clusters, never job_postings rows directly (see the
-- cluster-table comments in 20260817210000).

alter table job_postings alter column target_role drop not null;

comment on column job_postings.target_role is
  'Which of the 14 data/role_requirements.json role keys this fetch was '
  'searching for, NOT parsed from the listing itself. NULL for rows from a '
  'whole-board source (Workday, ATS fetchers) that pulls every posting at an '
  'employer rather than searching per role. Filtering only -- not part of the '
  'unique key, since one real listing can legitimately surface under more '
  'than one target_role search.';
