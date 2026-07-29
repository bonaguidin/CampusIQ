-- Grants anonymous read on the public reference tables (institutions,
-- grade_point_map). Not applied. Does not touch any frontend file.
--
-- RATIONALE: institutions and grade_point_map are public reference
-- data -- school names, IPEDS ids, grading scales, and brand colors.
-- They contain no student information. They were originally scoped to
-- the `authenticated` role by default rather than by decision, which
-- prevents the app from reading a school's grading scale or brand
-- colors before a session exists (e.g. to theme a login page per
-- institution, or resolve grade points, prior to sign-in). Granting
-- anon read is deliberate and safe: RLS stays enabled on both tables,
-- the new policies are SELECT-only, and no other policy on either
-- table permits anon writes (verified below -- each table has exactly
-- one pre-existing policy, and both are SELECT-only for `authenticated`
-- only, with no INSERT/UPDATE/DELETE/ALL policy of any kind).
--
-- Pre-existing policies found (read-only query against the live
-- database via `supabase db query --linked`, run before writing this
-- file):
--
--   tablename          | policyname                          | cmd    | roles           | qual | with_check
--   -------------------|--------------------------------------|--------|-----------------|------|------------
--   institutions       | institutions_read_authenticated       | SELECT | {authenticated} | true | null
--   grade_point_map    | grade_point_map_read_authenticated    | SELECT | {authenticated} | true | null
--
-- These are the only policies on either table (2 rows total across
-- both tables) -- names match what the original migration created, no
-- drift from assumption. rowsecurity was also confirmed true on both
-- tables via pg_tables before writing this migration.
--
-- This migration does NOT touch students, student_institutions,
-- academic_terms, course_records, career_profiles, certifications,
-- work_experience, or projects, or any policy on them. Those stay
-- session-scoped exactly as they are.

drop policy institutions_read_authenticated on institutions;

create policy institutions_read_public
  on institutions for select
  to anon, authenticated
  using (true);

drop policy grade_point_map_read_authenticated on grade_point_map;

create policy grade_point_map_read_public
  on grade_point_map for select
  to anon, authenticated
  using (true);

-- RLS remains ENABLED on both tables (not disabled by this migration).
-- An enabled table with a permissive SELECT-only policy is the correct
-- shape: reads are open, writes remain blocked by default since no
-- INSERT/UPDATE/DELETE policy exists for any role on either table.
