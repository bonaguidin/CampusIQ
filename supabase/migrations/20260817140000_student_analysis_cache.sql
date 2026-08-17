-- Adds student_analysis_cache: a persistent, Postgres-backed cache of GAP /
-- FIT / SHIFT results for real, authenticated (Postgres-backed) students.
--
-- ============================================================================
-- WHY THIS TABLE EXISTS, AND WHY IT DOES NOT COVER DEMO STUDENTS
-- ============================================================================
--
-- The five demo students (DEMO_STUDENT_SLUGS in GradusIQ_career/api.py) have
-- zero rows in `students` -- their data lives only in data/students/*.json.
-- A table keyed on `student_id references students (id)` cannot store a
-- result for them: there is no row to reference. Demo already has its own
-- working persistent cache -- the git-committed data/demo_cache/*.json files,
-- served cache-first by `_run_protected_feature` via `load_cached_feature_result`
-- -- and that mechanism is untouched by this migration. This table exists for
-- the other half of the population: real students, who have a `students` row
-- but, until now, no persisted GAP/FIT/SHIFT result at all -- every "Run
-- analysis" was a live call with nothing saved for the next page load.
--
-- ============================================================================
-- WHY `target_role` IS A CANONICAL STRING, NOT A SINGLE ROLE
-- ============================================================================
--
-- None of GAP, FIT, or SHIFT take a per-request target role. All three read
-- the full `career.target_roles` array off the student's profile
-- (GradusIQ_career/features/gap.py, fit.py, shift.py all do
-- `career.get("target_roles", [])`) -- none of them is role-agnostic, and
-- none of them can be cached per-role. `target_role` here instead captures
-- the whole target_roles *set* the result was computed against: the caller
-- sorts the array and joins it with "|" (see `_canonical_target_role` in
-- api.py). That way, if a student edits their target roles, the canonical
-- string changes, the old cache row's key no longer matches, and a stale
-- result computed against a different role set is never silently served as
-- current. In practice this column is not expected to be null -- FIT/GAP/SHIFT
-- already require a non-empty target_roles before they will run at all -- but
-- it is nullable defensively rather than assumed non-null by a constraint.
--
-- ============================================================================
-- UNIQUENESS AND NULLS NOT DISTINCT
-- ============================================================================
--
-- (student_id, feature, target_role) is the natural key: one cached result
-- per student, per feature, per role-set. target_role is nullable (see
-- above), and a plain unique constraint treats every NULL as distinct from
-- every other NULL, which would let a student accumulate multiple
-- null-target_role rows for the same (student_id, feature) instead of
-- upserting into one. As in course_records_student_term_course_key and
-- work_experience_student_employer_role_key
-- (20260728035418_natural_key_constraints_and_smu_grades.sql), this uses
-- `create unique index ... nulls not distinct` (PostgreSQL 17) so the upsert
-- in `_write_analysis_cache` has exactly one conflict target even on the
-- (practically unreachable) null-target_role path.

create table student_analysis_cache (
  id uuid primary key default gen_random_uuid(),
  student_id uuid not null references students (id),
  feature text not null check (feature in ('gap', 'fit', 'shift')),
  target_role text null,
  result jsonb not null,
  status text not null check (status in ('success', 'error')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

comment on table student_analysis_cache is
  'Persistent cache of GAP/FIT/SHIFT results for real (Postgres-backed) '
  'students only. Demo students (DEMO_STUDENT_SLUGS) have no students row and '
  'are served by the separate, pre-existing data/demo_cache/*.json mechanism '
  '-- this table does not, and cannot, cover them.';

comment on column student_analysis_cache.feature is
  'Lowercase feature name (''gap''/''fit''/''shift''), matching the URL '
  'segment used by /api/v2/student/me/analyze/{feature} and '
  '/api/v2/student/me/analysis-cache/{feature}. The RUNNERS dict in '
  'GradusIQ_career/features/orchestrator.py keys on the uppercase form '
  '(''GAP''/''FIT''/''SHIFT'') -- callers must lowercase at the write/read '
  'boundary rather than storing that casing here.';

comment on column student_analysis_cache.target_role is
  'Canonical representation of the student''s full career.target_roles array '
  'at the time this result was computed: sorted, then joined with "|". Not a '
  'single role -- GAP/FIT/SHIFT all consume the entire target_roles array and '
  'none of them is role-agnostic, so this column captures the whole set a '
  'change to which must invalidate the cached result. Nullable defensively; '
  'not expected to be null in practice since all three features already '
  'require a non-empty target_roles before running.';

comment on column student_analysis_cache.result is
  'The full FeatureResult JSON payload exactly as returned by the analyze '
  'endpoint (status/summary/data/errors/missing_fields) -- a cache hit is '
  'returned to the frontend unchanged, so this must stay byte-for-byte the '
  'same shape the live POST analyze endpoint produces.';

create unique index student_analysis_cache_student_feature_role_key
  on student_analysis_cache (student_id, feature, target_role)
  nulls not distinct;


-- ============================================================================
-- Row level security
-- ============================================================================

-- Student-owned data, so this follows the same owner-policy shape as
-- career_profiles / course_records (20260728000103_institution_grading_schema.sql
-- :236-267) and planned_courses (20260811120100_planned_courses.sql): a
-- student reads and writes only their own rows, resolved through
-- students.auth_user_id. FOR ALL rather than split policies -- there is no
-- privileged column here and no service-role-only write path to protect;
-- every write is either the student's own live analyze call or its cached
-- copy, written on the student's behalf through the same session.

alter table student_analysis_cache enable row level security;

create policy student_analysis_cache_owner_all
  on student_analysis_cache for all
  to authenticated
  using (
    exists (
      select 1 from students
      where students.id = student_analysis_cache.student_id
        and students.auth_user_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1 from students
      where students.id = student_analysis_cache.student_id
        and students.auth_user_id = auth.uid()
    )
  );

-- anon gets no policy at all, so PostgreSQL default-denies every command for
-- it. The grant is stripped as well, matching planned_courses -- policy and
-- grant are independent, and leaving the default `GRANT ALL` in place would
-- mean only the policy stands between anon and a write.

revoke insert, update, delete, truncate on student_analysis_cache from anon;
revoke select on student_analysis_cache from anon;


-- ============================================================================
-- Index
-- ============================================================================

-- The read pattern is "this student's cached result for one feature" (the GET
-- analysis-cache route filters student_id + feature, then narrows by
-- target_role in the application layer / via the unique index above). The
-- unique index already covers (student_id, feature, target_role) as its
-- leading columns, but a plain non-unique index on the (student_id, feature)
-- prefix keeps a feature-only lookup index-only without depending on the
-- unique index's null-handling semantics.
create index student_analysis_cache_student_feature_idx
  on student_analysis_cache (student_id, feature);
