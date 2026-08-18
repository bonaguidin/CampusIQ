-- DRAFT -- staged, NOT applied. Written for review alongside
-- scripts/job_postings/{adzuna_client,jsearch_client}.py, ahead of any real
-- fetch-scheduler or FIT/SHIFT integration. Do not run `supabase migration up`
-- against this file until Deepak has reviewed it.
--
-- Adds job_postings (fetched listings, deduped per vendor) and
-- job_posting_fetch_log (one row per fetch attempt, for quota accounting and
-- staleness detection) -- the schema outstanding-fixes.md's "Job posting
-- data" section calls for before any live vendor integration can exist:
-- cache-first architecture is a hard requirement given Adzuna's ~1,000/mo and
-- JSearch's ~200/mo free-tier quotas, not an optimization.
--
-- ============================================================================
-- PRECEDENT CHECK -- FLAG FOR DEEPAK: THIS IS NOT A DROP-IN-THE-SAME-PATTERN
-- MIGRATION, IT IS THE FIRST OF ITS KIND
-- ============================================================================
--
-- The two datasets this task's brief pointed to as precedent --
-- role_research_cache and the O*NET reference catalog -- are BOTH flat JSON
-- files (data/.cache/role_research_cache.json,
-- data/reference/onet_soc_requirements.json), confirmed by grepping every
-- migration under supabase/migrations/ for either name: zero matches. Neither
-- has ever lived in Postgres. There is no "shared reference data skips RLS"
-- precedent to inherit from them, because neither of them went through RLS
-- at all -- they went through the filesystem instead.
--
-- The precedent that DOES exist, for every genuinely-public reference table
-- actually built in Postgres so far (institutions, grade_point_map,
-- academic_term_dates, course_catalog), is the opposite of "no RLS": each
-- enables RLS and adds exactly one permissive SELECT policy for
-- {anon, authenticated}, paired with a revoke of anon's write grants
-- (20260801175516_revoke_anon_writes_on_reference_tables.sql;
-- academic_term_dates repeats the same pair inline). job_postings below
-- follows THAT established convention rather than the "no RLS" assumption
-- this migration was originally briefed with, since it is public
-- job-listing data with the same shape (service-role-written, read by
-- anyone) as those tables.
--
-- job_posting_fetch_log is different: it's an internal operational log (call
-- counts, quota usage, error detail from a vendor), not something a
-- frontend page needs to read. RLS is enabled with NO policies at all, so it
-- defaults to deny for anon/authenticated and stays readable/writable only
-- by the service role (which bypasses RLS entirely, same as every fetch
-- script in this repo that writes with SUPABASE_SECRET_KEY).
--
-- Net: if this table set is built, job_postings would be this repo's first
-- reference dataset to move from flat-file to Postgres. Worth Deepak's
-- explicit sign-off on that move alone, independent of the RLS question
-- above -- it's a bigger decision than "which policy shape."
--
-- ============================================================================
-- DEDUP / CACHE-KEY DESIGN
-- ============================================================================
--
-- unique (source, source_job_id) is the vendor-native identity: Adzuna and
-- JSearch both hand back a per-listing id that is stable across repeat
-- fetches of the same posting, so re-fetching the same search a week later
-- and upserting on this key is how the same listing avoids duplicating
-- rather than accumulating one row per fetch. It is NOT unique on
-- (source, target_role, source_job_id) -- a posting fetched under two
-- different target_role queries (plausible: a hybrid SWE/hardware intern
-- posting could surface under both "Software Engineering Intern" and
-- "Computer Engineering Intern" searches) is the same real-world listing and
-- should stay one row, not fork per query. target_role is kept as a plain
-- column for filtering, not folded into the identity.
--
-- fetched_at (not source_job_id alone) is what a TTL/staleness check reads:
-- outstanding-fixes.md flags "no TTL primitive exists anywhere in the
-- codebase" as a specific gap for posting data, which goes stale in days,
-- not years like O*NET. A consumer asking "is this posting data fresh
-- enough to show" compares now() - fetched_at against a TTL constant, not
-- posted_date (the vendor's own listing date, which is metadata about the
-- posting, not about when GradusIQ last saw it).
--
-- job_posting_fetch_log is the OTHER half of the TTL/quota answer: "when did
-- we last fetch target_role X from source Y, and how many quota units did
-- that cost" -- a fetch scheduler reads the latest row per (source,
-- target_role) to decide whether a re-fetch is due, without having to
-- infer that from job_postings.fetched_at aggregates (which would silently
-- go blank for a target_role/source pair that returned zero results, a
-- state fetch_log's results_count=0 + status='success' represents
-- explicitly, that job_postings alone cannot represent as a row).

create table job_postings (
  id uuid primary key default gen_random_uuid(),
  source text not null check (source in ('adzuna', 'jsearch')),
  source_job_id text not null,
  title text not null,
  company text,
  location text,
  target_role text not null,
  skills_extracted jsonb not null default '[]'::jsonb,
  salary_min numeric,
  salary_max numeric,
  posted_date date,
  fetched_at timestamptz not null default now(),
  raw_payload jsonb not null,
  created_at timestamptz not null default now(),
  unique (source, source_job_id),
  constraint job_postings_salary_range check (
    salary_min is null or salary_max is null or salary_max >= salary_min
  )
);

comment on table job_postings is
  'Fetched job listings from Adzuna/JSearch, deduped per vendor listing id. '
  'Shared reference data, not student-owned -- see the precedent-check note '
  'above this table''s CREATE statement for the RLS rationale.';

comment on column job_postings.source_job_id is
  'The vendor''s own listing id (Adzuna: "id"; JSearch: "job_id"). Paired '
  'with source as the true identity -- see the dedup design note above.';

comment on column job_postings.target_role is
  'Which of the 14 data/role_requirements.json role keys this fetch was '
  'searching for, NOT parsed from the listing itself. Filtering only -- not '
  'part of the unique key, since one real listing can legitimately surface '
  'under more than one target_role search.';

comment on column job_postings.skills_extracted is
  'Reserved for a future extraction step (e.g. parsed off raw_payload''s '
  'description text). Defaults to an empty array; nothing populates it yet.';

comment on column job_postings.fetched_at is
  'When GradusIQ last fetched this listing -- the TTL/staleness field. '
  'Distinct from posted_date, which is the vendor''s own listing date.';

comment on column job_postings.raw_payload is
  'The full vendor response for this listing, kept verbatim so a future '
  'extraction pass (skills_extracted, or a field nobody thought to promote '
  'to a column yet) can be re-run without re-fetching from the vendor.';


create table job_posting_fetch_log (
  id uuid primary key default gen_random_uuid(),
  source text not null check (source in ('adzuna', 'jsearch')),
  target_role text not null,
  fetched_at timestamptz not null default now(),
  results_count integer not null check (results_count >= 0),
  quota_used integer not null default 1 check (quota_used >= 0),
  status text not null check (status in ('success', 'error')),
  error_detail text
);

comment on table job_posting_fetch_log is
  'One row per fetch attempt against a vendor, for quota accounting '
  '(Adzuna ~1,000/mo, JSearch ~200/mo -- see outstanding-fixes.md''s "Job '
  'posting data" section) and staleness checks. Internal/operational --  '
  'unlike job_postings, nothing here is meant for a frontend page to read '
  'directly, hence no public SELECT policy below.';

comment on column job_posting_fetch_log.results_count is
  'How many listings this fetch returned, INCLUDING zero. A target_role/'
  'source pair that legitimately has no matches still gets a row here with '
  'results_count=0 and status=''success'' -- distinct from status=''error'', '
  'where the vendor call itself failed and results_count should be read as '
  '"unknown", not "zero".';

comment on column job_posting_fetch_log.quota_used is
  'Vendor quota units this fetch consumed. Defaults to 1 (one call = one '
  'unit for both Adzuna and JSearch''s simple per-request pricing); kept as '
  'its own column rather than assumed constant so a future paginated fetch '
  '(quota_used > 1 per logical target_role/source fetch) doesn''t need a '
  'schema change to report itself accurately.';

comment on column job_posting_fetch_log.error_detail is
  'Vendor error message or exception text when status=''error''. Null on '
  'success.';


-- ============================================================================
-- Row level security
-- ============================================================================

-- job_postings: public-read reference data, same posture as institutions,
-- grade_point_map, academic_term_dates, course_catalog -- see the
-- precedent-check note above. Writes happen only via a fetch script running
-- under SUPABASE_SECRET_KEY, which bypasses RLS as the service role.

alter table job_postings enable row level security;

create policy job_postings_read_public
  on job_postings for select
  to anon, authenticated
  using (true);

-- Companion to 20260801175516_revoke_anon_writes_on_reference_tables.sql:
-- strip the Supabase-default `GRANT ALL` write grants at creation time
-- rather than as a later cleanup pass, so this table is never anon-writable
-- even transiently. SELECT is deliberately NOT revoked -- the policy above
-- depends on it.

revoke insert, update, delete, truncate on job_postings from anon;

-- job_posting_fetch_log: RLS enabled, NO policies added. PostgreSQL RLS
-- default-denies any command with no permissive policy, so this table is
-- unreadable and unwritable by anon/authenticated and reachable only by the
-- service role -- deliberate, since this is an internal operational log (see
-- the table comment), not data any page needs to render.

alter table job_posting_fetch_log enable row level security;


-- ============================================================================
-- Indexes
-- ============================================================================

-- "Latest fetch per (source, target_role)" is job_posting_fetch_log's one
-- real access pattern -- a scheduler asking "is a re-fetch due" reads this
-- before deciding to spend quota. DESC on fetched_at so LIMIT 1 against this
-- index answers it directly.

create index job_posting_fetch_log_source_role_fetched_idx
  on job_posting_fetch_log (source, target_role, fetched_at desc);

-- job_postings' own access pattern is "this target_role's postings, freshest
-- first" -- whatever eventually reads this table for FIT/SHIFT grounding
-- asks for one role at a time, not the whole table.

create index job_postings_target_role_fetched_idx
  on job_postings (target_role, fetched_at desc);
