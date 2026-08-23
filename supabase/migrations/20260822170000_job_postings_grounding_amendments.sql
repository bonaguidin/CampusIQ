-- DRAFT -- staged, NOT applied. Follow-up to
-- 20260817210000_job_postings_reference_draft.sql.
--
-- WHY THIS FILE EXISTS RATHER THAN JUST RE-RUNNING THE OLD ONE:
-- 20260817210000 was applied to production containing only Deepak's original
-- 2-table draft (job_postings, job_posting_fetch_log -- no url/is_dfw/
-- location_kind/posting_identity columns, no ATS platforms in `source`, no
-- posting_clusters/posting_identity_keys/posting_cluster_merges/employers).
-- The file was later amended IN PLACE on feat/postings-grounding to add the
-- ATS-source and cross-source-identity schema, but Supabase's migration
-- tracker records history by version/filename, not content -- so it already
-- considers 20260817210000 satisfied and a plain `supabase migration up`
-- would skip it, silently never applying the amendments. This migration
-- carries exactly that delta: the gap between what's live and what
-- 20260817210000's current (amended) content actually specifies.
--
-- Confirmed against the live database read-only (PostgREST) before writing
-- this file, not assumed:
--   - job_postings and job_posting_fetch_log exist, with exactly the
--     original draft's columns.
--   - posting_clusters, posting_identity_keys, posting_cluster_merges,
--     employers do not exist.
--
-- Do not run `supabase migration up` against this file until Deepak has
-- reviewed it -- same posture as the file it follows.
--
-- ============================================================================
-- NON-ADDITIVE CHANGES IN THIS DELTA -- READ BEFORE RUNNING
-- ============================================================================
--
-- Two of the four changes below are not simple ADD COLUMN:
--
-- 1. job_postings.raw_payload: was `jsonb not null`, relaxed to nullable.
-- 2. job_posting_fetch_log.target_role: was `text not null`, relaxed to
--    nullable (an ATS fetch loops employers, not target roles -- see the
--    has_subject constraint below).
--
-- Both are safe regardless of existing row state (relaxing NOT NULL cannot
-- violate anything), and doubly safe here since both tables are confirmed
-- empty live as of this writing.
--
-- The other two are CHECK constraint replacements, not additions:
--
-- 3 & 4. job_postings.source and job_posting_fetch_log.source: both widen
--    from `in ('adzuna', 'jsearch')` to the full 8-platform list. Both
--    constraints were written inline/unnamed in the original CREATE TABLE,
--    so this migration assumes Postgres's default naming convention
--    (`<table>_source_check`) to drop them. That name was NOT independently
--    verified against pg_constraint -- no raw SQL access was available to
--    confirm it (only PostgREST reads; `supabase db dump` requires Docker,
--    which isn't available in this environment). The DROP is IF EXISTS, so
--    a wrong guess is a safe no-op rather than a failure -- but the ADD
--    that follows would then also fail with "constraint already exists" if
--    the old one is still there under a different name. Verify with:
--      select conname from pg_constraint
--       where conrelid = 'job_postings'::regclass and contype = 'c';
--    (and the same for job_posting_fetch_log) before running this.
--
-- ============================================================================


-- ----------------------------------------------------------------------------
-- job_postings -- new columns
-- ----------------------------------------------------------------------------

alter table job_postings add column if not exists url text;
alter table job_postings add column if not exists is_dfw boolean;
alter table job_postings add column if not exists location_kind text;
alter table job_postings add column if not exists posting_identity uuid;

comment on column job_postings.url is
  'Link to the live posting. Load-bearing for dedup, not just for humans: '
  'ATS URLs embed the job id in the path '
  '(job-boards.greenhouse.io/pmg/jobs/8496729002), so a vendor listing that '
  'links back to an ATS board can recover that board''s own external id and '
  'match a row already fetched directly. See data/ats_fetcher/DEDUP.md §3.1.';

comment on column job_postings.is_dfw is
  'Whether this posting is in the DFW metro, derived from location at '
  'ingest. Cluster matching uses this rather than the raw location string, '
  'which syndicators rewrite freely. Always a definite verdict where a '
  'location was given -- location_kind carries the reasoning, so a contested '
  'call can be reversed later without re-deriving anything.';

comment on column job_postings.location_kind is
  'Why is_dfw is what it is. dfw_metro / multi_includes_dfw / hybrid_dfw are '
  'the true cases; texas_non_dfw / remote_us / remote_anywhere / non_dfw are '
  'the false ones; unknown means no usable location was given. The remote '
  'cases are the point: they are false today, and flipping that is an UPDATE '
  'on this column rather than a re-pull.';

comment on column job_postings.posting_identity is
  'Which cluster of cross-source duplicates this row belongs to. Mutable by '
  'design: a vendor can deliver a listing before the employer''s own ATS '
  'feed surfaces it, and the later ATS row is the exact evidence that two '
  'clusters are one. Null until the identity pass has run on this row.';

-- location_kind's value-set CHECK, added separately since ADD COLUMN doesn't
-- take a CHECK inline when the column may already exist from a prior partial
-- run. duplicate_object here means the constraint is already in place.
do $$
begin
  alter table job_postings add constraint job_postings_location_kind_check
    check (location_kind is null or location_kind in (
      'dfw_metro', 'multi_includes_dfw', 'hybrid_dfw',
      'texas_non_dfw', 'remote_us', 'remote_anywhere', 'non_dfw', 'unknown'
    ));
exception
  when duplicate_object then null;
end $$;


-- ----------------------------------------------------------------------------
-- job_postings -- non-additive: raw_payload relaxed to nullable
-- ----------------------------------------------------------------------------
--
-- Was `not null` in the applied original. Retention (90-day rolling window,
-- see scripts/job_postings/retention.py) nulls this column on aged rows
-- rather than deleting them -- see note 5 in 20260817210000's header.

alter table job_postings alter column raw_payload drop not null;


-- ----------------------------------------------------------------------------
-- job_postings -- non-additive: source CHECK widened to the 8 ATS platforms
-- ----------------------------------------------------------------------------
-- See the NON-ADDITIVE CHANGES note at the top of this file re: constraint
-- name assumption. Verify before running.

alter table job_postings drop constraint if exists job_postings_source_check;

do $$
begin
  alter table job_postings add constraint job_postings_source_check
    check (source in (
      'adzuna', 'jsearch',
      'greenhouse', 'lever', 'ashby', 'smartrecruiters', 'recruitee',
      'workday'
    ));
exception
  when duplicate_object then null;
end $$;


-- ----------------------------------------------------------------------------
-- job_posting_fetch_log -- new column, relaxed constraint, new CHECK
-- ----------------------------------------------------------------------------
-- AMENDED reasoning (from 20260817210000): an ATS run loops employers, not
-- target roles, so target_role becomes nullable and employer joins it, with
-- a check that a row carries at least one of the two.

alter table job_posting_fetch_log add column if not exists employer text;

comment on column job_posting_fetch_log.employer is
  'Which employer this fetch attempt targeted, for ATS-sourced runs. Null '
  'for vendor (Adzuna/JSearch) fetches, which are per-target_role instead -- '
  'see job_posting_fetch_log_has_subject below.';

alter table job_posting_fetch_log alter column target_role drop not null;

do $$
begin
  alter table job_posting_fetch_log
    add constraint job_posting_fetch_log_has_subject
    check (target_role is not null or employer is not null);
exception
  when duplicate_object then null;
end $$;

-- Same source-platform widening as job_postings, same name-assumption
-- caveat -- see the NON-ADDITIVE CHANGES note at the top of this file.

alter table job_posting_fetch_log
  drop constraint if exists job_posting_fetch_log_source_check;

do $$
begin
  alter table job_posting_fetch_log add constraint job_posting_fetch_log_source_check
    check (source in (
      'adzuna', 'jsearch',
      'greenhouse', 'lever', 'ashby', 'smartrecruiters', 'recruitee',
      'workday'
    ));
exception
  when duplicate_object then null;
end $$;


-- ----------------------------------------------------------------------------
-- posting_clusters -- the layer above (source, source_job_id)
-- ----------------------------------------------------------------------------
-- One row per real-world job, however many sources sent it. job_postings
-- rows point here via posting_identity. See data/ats_fetcher/DEDUP.md.
-- Counting reads clusters; it must never read job_postings rows directly.

create table if not exists posting_clusters (
  id uuid primary key default gen_random_uuid(),
  canonical_posting_id uuid,
  match_rule text not null check (match_rule in ('ats_url_id', 'fuzzy', 'seed')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

comment on table posting_clusters is
  'One row per real-world job posting, grouping job_postings rows that came '
  'from different sources. See data/ats_fetcher/DEDUP.md for the identity '
  'rules. Counting iterates clusters, never job_postings rows.';

comment on column posting_clusters.canonical_posting_id is
  'Which job_postings row represents this cluster. The ATS row always wins '
  'where one exists -- it is the employer''s own feed, so the title is '
  'unrewritten and the posting date is real. Where the cluster is vendor-only, '
  'a fixed configured vendor order decides, so output does not depend on which '
  'source happened to answer first on a given night.';

comment on column posting_clusters.match_rule is
  'How this cluster was formed. ats_url_id is the exact path: an ATS job id '
  'recovered from a vendor listing''s apply URL, matched against a row already '
  'fetched from that board -- no threshold, no false positives. fuzzy is the '
  'employer/title/is_dfw fallback for vendor-native postings, which will '
  'sometimes over-merge and is accepted as failing in the conservative '
  'direction. seed means the cluster started from a single row with no match.';

-- Cross-referencing FKs, added after both tables exist. job_postings'
-- posting_identity column was added earlier in this file without its FK,
-- specifically so it could be added here once posting_clusters exists.

do $$
begin
  alter table job_postings
    add constraint job_postings_posting_identity_fkey
    foreign key (posting_identity) references posting_clusters (id)
    on delete set null;
exception
  when duplicate_object then null;
end $$;

create index if not exists job_postings_posting_identity_idx
  on job_postings (posting_identity);

do $$
begin
  alter table posting_clusters
    add constraint posting_clusters_canonical_posting_fkey
    foreign key (canonical_posting_id) references job_postings (id)
    on delete set null;
exception
  when duplicate_object then null;
end $$;


-- ----------------------------------------------------------------------------
-- posting_identity_keys -- how a cluster is found again
-- ----------------------------------------------------------------------------
-- Key format owned by scripts/job_postings/identity.py:
--   ats:<board>:<external_id>          exact, recovered from an apply URL
--   fuzzy:<employer>:<title>:<bucket>  inferred

create table if not exists posting_identity_keys (
  key text primary key,
  cluster_id uuid not null references posting_clusters (id) on delete cascade,
  created_at timestamptz not null default now()
);

comment on table posting_identity_keys is
  'Identity key -> cluster. Primary key on `key` is what makes a lookup exact '
  'rather than a substring search, and what stops two clusters from claiming '
  'the same key. See data/ats_fetcher/DEDUP.md.';

create index if not exists posting_identity_keys_cluster_idx
  on posting_identity_keys (cluster_id);


-- ----------------------------------------------------------------------------
-- posting_cluster_merges -- why two clusters became one
-- ----------------------------------------------------------------------------

create table if not exists posting_cluster_merges (
  id uuid primary key default gen_random_uuid(),
  absorbed_cluster_id uuid not null,
  surviving_cluster_id uuid not null references posting_clusters (id) on delete cascade,
  match_rule text not null check (match_rule in ('ats_url_id', 'fuzzy')),
  triggered_by_posting_id uuid references job_postings (id) on delete set null,
  merged_at timestamptz not null default now(),
  constraint posting_cluster_merges_distinct check (
    absorbed_cluster_id <> surviving_cluster_id
  )
);

comment on table posting_cluster_merges is
  'Audit trail for cluster merges. absorbed_cluster_id is deliberately NOT a '
  'foreign key -- the row it pointed at is gone by the time the merge is '
  'recorded, and keeping the dead id readable is the entire point of the log.';


-- ----------------------------------------------------------------------------
-- employers -- the DFW list
-- ----------------------------------------------------------------------------
-- Not loadable yet: data/job_postings/dfw_employers_ats.csv has not been
-- imported via scripts/job_postings/load_employers.py.

create table if not exists employers (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  slug text,
  sector text,
  dfw_location text,
  domain text,
  ats_platform text check (ats_platform is null or ats_platform in (
    'greenhouse', 'lever', 'ashby', 'smartrecruiters', 'recruitee', 'workday',
    'icims', 'oracle_cloud', 'taleo', 'successfactors', 'avature',
    'eightfold', 'ukg', 'talent_community', 'proprietary'
  )),
  priority integer,
  checked_date date,
  notes text,
  target_role_families jsonb not null default '[]'::jsonb,
  confirmed_roles jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (name)
);

comment on column employers.priority is
  'Research tier from the source CSV, 1-5. Work-ordering for slug lookup, not '
  'a ranking of the employer.';

comment on column employers.checked_date is
  'When someone last confirmed this employer''s ATS board actually exists and '
  'is on the platform claimed. Null for every row in the initial load -- see '
  'the note on slug below.';

comment on column employers.notes is
  'Free text from the source CSV. Mostly hypotheses about which ATS an '
  'employer is likely on ("Enterprise HCM likely -- check for '
  'myworkdayjobs.com"), which is research to be done rather than fact.';

comment on column employers.slug is
  'The identifier in the employer''s own careers URL, and the thing the ATS '
  'fetcher cannot work without. NULL for all 44 rows of the initial load: '
  'that column was never filled in. So this table currently describes who to '
  'target, not who can be fetched.';

comment on column employers.ats_platform is
  'Nullable on purpose: the source CSV has this column only partly filled, '
  'and an unknown ATS is a real state rather than a data error. An employer '
  'with a null platform simply is not reachable by the ATS fetcher yet.';

comment on column employers.target_role_families is
  'Which role families this employer was picked as a target for -- an '
  'assumption carried in from the hand-built list.';

comment on column employers.confirmed_roles is
  'Role families for which a real posting has actually come back from this '
  'employer. Starts empty and only ever grows from evidence. The difference '
  'between this and target_role_families is the difference between what the '
  'list guessed and what the corpus proved.';


-- ----------------------------------------------------------------------------
-- Row level security -- new tables
-- ----------------------------------------------------------------------------
--
-- employers follows job_postings: public-read reference data, service-role
-- writes -- matches the institutions / grade_point_map / course_catalog
-- convention the precedent check in 20260817210000 established.

alter table employers enable row level security;

do $$
begin
  create policy employers_read_public
    on employers for select
    to anon, authenticated
    using (true);
exception
  when duplicate_object then null;
end $$;

revoke insert, update, delete, truncate on employers from anon;

-- posting_clusters, posting_cluster_merges and posting_identity_keys follow
-- job_posting_fetch_log: RLS enabled, no policies, default-deny to anon and
-- authenticated, service-role only. Matches ingest.py's documented posture
-- verbatim (see its module docstring): "posting_clusters denies everyone
-- but the service role outright." All three are ingest-internal
-- bookkeeping -- anything a page needs reaches job_postings through
-- posting_identity, which is already public-readable.

alter table posting_clusters enable row level security;
alter table posting_cluster_merges enable row level security;
alter table posting_identity_keys enable row level security;


-- ----------------------------------------------------------------------------
-- Indexes -- amended access patterns
-- ----------------------------------------------------------------------------

-- The exact-match dedup path looks up "have I already stored this URL", once
-- per incoming vendor listing per night. Partial, since rows with no URL are
-- never probed this way.

create index if not exists job_postings_url_idx
  on job_postings (url)
  where url is not null;

-- The retention job asks for rows whose payload is older than the window and
-- has not already been nulled. Partial for the same reason: once a payload
-- is nulled the row never qualifies again, so it should not stay in the
-- index.

create index if not exists job_postings_raw_payload_age_idx
  on job_postings (fetched_at)
  where raw_payload is not null;
