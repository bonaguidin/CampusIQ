-- Provenance and review-state tracking for the four career-side tables, plus
-- a check constraint on certifications.status.
--
-- Verification (2026-08-01, read-only against the live database, immediately
-- before writing this file):
--   * Of the columns added below, only career_profiles.updated_at already
--     existed. No source, confirmed_at, or updated_at column exists on
--     certifications, work_experience, or projects.
--   * certifications has ZERO check constraints (only pkey, a unique on
--     (student_id, name), and the composite FK to career_profiles).
--   * All 9 certifications rows satisfy the proposed status check
--     (5 'completed', 4 'in_progress', 0 NULL, 0 that would fail), so the
--     ADD CONSTRAINT below validates cleanly against existing data.
--   * Every row in all four tables belongs to one of the 5 demo students
--     (5 distinct student_id values per table, 5 rows in students), so the
--     backfill in section 4 covers exactly those students.
--   * The public schema has ZERO user triggers and ZERO trigger functions --
--     see section 2 on why this migration does not add one.
--
-- Not applied. DDL and backfill only.

-- ============================================================================
-- 1. source + confirmed_at
-- ============================================================================

-- Unconfirmed rows (confirmed_at is null) represent parser output pending
-- student review and should not be treated as authoritative by FIT/GAP/SHIFT
-- until confirmed. Mirrors the existing course_records.source/confirmed_at
-- pattern.
--
-- The vocabulary deliberately differs from course_records', which is
-- ('transcript_parse', 'manual', 'canvas'). Career-side rows can originate
-- from a resume upload but never from Canvas, so 'canvas' is omitted and
-- 'resume_parse' added. 'transcript_parse' is retained: a transcript can
-- evidence a certification.
--
-- Both columns are nullable, unlike course_records.source which is NOT NULL.
-- These tables already hold 29 rows with no provenance recorded; a NOT NULL
-- column would require choosing a value for them at DDL time rather than in
-- the explicit, auditable backfill in section 4.

alter table career_profiles
  add column source text null
    check (source in ('manual', 'resume_parse', 'transcript_parse')),
  add column confirmed_at timestamptz null;

alter table certifications
  add column source text null
    check (source in ('manual', 'resume_parse', 'transcript_parse')),
  add column confirmed_at timestamptz null;

alter table work_experience
  add column source text null
    check (source in ('manual', 'resume_parse', 'transcript_parse')),
  add column confirmed_at timestamptz null;

alter table projects
  add column source text null
    check (source in ('manual', 'resume_parse', 'transcript_parse')),
  add column confirmed_at timestamptz null;

-- ============================================================================
-- 2. updated_at
-- ============================================================================

-- career_profiles already has updated_at; the other three do not. Added as
-- NOT NULL DEFAULT now() so new rows are always stamped, then backfilled to
-- created_at so existing rows report when they were actually written rather
-- than when this migration ran.
--
-- NO TRIGGER IS ADDED. Verified above: the public schema contains zero user
-- triggers and zero trigger functions, so nothing currently auto-maintains
-- updated_at anywhere -- not on career_profiles, not on course_records, not on
-- students. Those columns are maintained by the writing application, or not at
-- all. Introducing a trigger here would make these three tables behave
-- differently from every other table in the schema, so this migration matches
-- the existing convention instead. If auto-maintenance is wanted, it should be
-- added everywhere at once, in its own migration.

alter table certifications
  add column updated_at timestamptz not null default now();

alter table work_experience
  add column updated_at timestamptz not null default now();

alter table projects
  add column updated_at timestamptz not null default now();

-- Backfill: existing rows have never been updated, so updated_at = created_at.
update certifications set updated_at = created_at;
update work_experience set updated_at = created_at;
update projects set updated_at = created_at;

-- ============================================================================
-- 3. certifications.status check constraint
-- ============================================================================

-- certifications.status has carried the same two-value vocabulary as
-- course_records.status ('completed', 'in_progress') since it was created, but
-- unlike course_records it has never had a constraint enforcing it -- the data
-- has stayed clean by convention alone. This closes that gap.
--
-- Stays NULLABLE: the column is nullable today and holds no NULLs, but a
-- certification with no recorded status is legitimate (a student may not know
-- whether a lapsed credential counts as complete). `status is null or ...`
-- permits that rather than forcing a value onto rows that lack one.
--
-- course_records' own constraint is NOT NULL-permitting for contrast:
--   CHECK (status = ANY (ARRAY['completed'::text, 'in_progress'::text]))
-- because course_records.status is declared NOT NULL. The difference is
-- deliberate, not an inconsistency.

alter table certifications
  add constraint certifications_status_check
    check (status is null or status in ('completed', 'in_progress'));

-- ============================================================================
-- 4. Backfill provenance for existing demo rows
-- ============================================================================

-- Every existing row in these four tables was hand-authored as demo fixture
-- data (see data/students/student_<slug>.json, all five labelled "Mock Canvas
-- LMS data"), so 'manual' is accurate provenance. They are treated as
-- student-confirmed because they represent a completed, reviewed profile --
-- FIT/GAP/SHIFT already consume them as authoritative today, and leaving
-- confirmed_at null would retroactively demote data those features rely on.
--
-- Scoped with `where source is null` so the backfill is idempotent and cannot
-- overwrite provenance on any row written between this file being authored and
-- being applied.

update career_profiles
set source = 'manual', confirmed_at = now()
where source is null;

update certifications
set source = 'manual', confirmed_at = now()
where source is null;

update work_experience
set source = 'manual', confirmed_at = now()
where source is null;

update projects
set source = 'manual', confirmed_at = now()
where source is null;
