-- Constrains the two free-text columns the profile-completion surface writes:
-- career_profiles.ai_anxiety_level becomes a four-value vocabulary, and
-- students.expected_graduation becomes a canonical "Season YYYY" string.
--
-- Phase 2, Step 1 of the profile-completion surface. Backfill + constraints
-- only: no new columns, no route, no page.
--
-- ============================================================================
-- VERIFICATION (2026-08-12, read-only against the live database, run
-- immediately before writing this file)
-- ============================================================================
--
-- 1. students: 9 rows. expected_graduation is set on 5 and NULL on 4.
--    Every one of the 5 matches ^[0-9]{4}-05$ exactly:
--      Ethan Brooks   '2029-05'      Marcus Webb   '2028-05'
--      Jordan Reyes   '2029-05'      Priya Nair    '2028-05'
--                                    Sofia Ramirez '2028-05'
--    DISTINCT MONTHS PRESENT: {'05'} only. There is no value with a month
--    other than 05, so the Spring mapping in section 2 is total rather than
--    a majority rule with a tail this migration would have to guess at.
--
-- 2. career_profiles: 7 rows (2 of the 9 students have no row at all).
--    ai_anxiety_level is set on 5 and NULL on 2. Every set value has the
--    shape '<level> — <prose>' with a U+2014 em-dash, and every prefix is
--    already one of the target values:
--      moderate x4 (Ethan Brooks, Jordan Reyes, Marcus Webb, Sofia Ramirez)
--      low      x1 (Priya Nair)
--    There is no 'high' and no 'not_sure' on file, and NO UNMAPPABLE PREFIX.
--
-- 3. All 7 career_profiles rows have confirmed_at set. No schema change is
--    needed for the Step 2 route to stamp confirmed_at on write -- the column
--    already exists (added in 20260801190523) and is nullable.
--
-- 4. students.major_current and students.major_intended already exist, are
--    already `text null`, and need NO change for this surface. They are named
--    here only so their absence below reads as a decision rather than an
--    oversight. In particular NO constraint is added to major_intended: the
--    literal string 'N/A' is live in 3 rows and is load-bearing (see
--    _NO_INTENDED_MAJOR in GradusIQ_career/features/fit.py), so any
--    vocabulary constraint would either reject it or bless it, and neither
--    belongs in a migration about formats.
--
-- ============================================================================
-- WHY CHECK CONSTRAINTS AND NOT POSTGRES ENUM TYPES
-- ============================================================================
--
-- The schema contains ZERO `create type ... as enum` and constrains all 13 of
-- its existing vocabularies with CHECK ... IN (...) -- course_records.status,
-- course_records.source, student_institutions.relationship,
-- academic_term_dates.season, and so on. Matching that is not only
-- consistency: adding a value to a CHECK is one ALTER in a migration, while
-- ALTER TYPE ... ADD VALUE cannot run inside a transaction block and cannot be
-- removed at all. 'not_sure' exists precisely because this vocabulary is
-- expected to be revised once real students answer it.
--
-- Both constraints permit NULL explicitly, following
-- certifications_status_check (20260801190523 section 3). NULL is not a
-- rejected value here, it is the meaningful one: it means the student has
-- never been asked. 'not_sure' is a different state -- they were asked and
-- said they do not know -- and the profile-completion surface must be able to
-- tell those apart to know whether to prompt.
--
-- ============================================================================
-- ORDERING: BACKFILL FIRST, CONSTRAIN SECOND
-- ============================================================================
--
-- ALTER TABLE ... ADD CONSTRAINT validates against every existing row at the
-- moment it runs. Both columns hold data that the new constraints reject --
-- all 5 ai_anxiety_level values are prose, all 5 expected_graduation values
-- are 'YYYY-MM' -- so adding either constraint before its backfill would abort
-- the migration with a check_violation and leave nothing applied.
--
-- Each section below therefore runs UPDATE first and ALTER second, and each
-- is preceded by a guard that raises if any row would still violate. The
-- guards are not redundant with the constraints: a guard names the offending
-- value in its message, whereas the constraint reports only that some row
-- failed. On a migration whose whole risk is unmapped input, that difference
-- is the difference between a two-minute fix and a hunt.

-- ============================================================================
-- 1. career_profiles.ai_anxiety_level -> low | moderate | high | not_sure
-- ============================================================================

-- Takes the text before the first dash and lowercases it, which turns
-- 'moderate — curious about business uses of AI...' into 'moderate'. The
-- prose after the dash is DROPPED, deliberately and irreversibly: it was
-- authored as demo fixture data, no feature reads it as anything but an opaque
-- string, and preserving it in a second column would create a field the new
-- surface has no way to collect and no place to show.
--
-- The pattern matches an em-dash (U+2014), en-dash (U+2013) or ASCII hyphen so
-- it does not depend on which one the fixture author happened to type.
-- Anchored with .*$ so only the FIRST dash splits: a value whose prose itself
-- contains a dash still yields the leading level.

update career_profiles
set ai_anxiety_level = lower(btrim(regexp_replace(ai_anxiety_level, '\s*[—–-].*$', '')))
where ai_anxiety_level is not null;

-- Guard: fail loudly, naming the value, if anything did not land in the
-- vocabulary. Verified to affect 0 rows today; it exists for the case where
-- this file is applied against a database that has drifted from the one
-- verified above.
do $$
declare
  bad text;
begin
  select ai_anxiety_level into bad
  from career_profiles
  where ai_anxiety_level is not null
    and ai_anxiety_level not in ('low', 'moderate', 'high', 'not_sure')
  limit 1;

  if bad is not null then
    raise exception
      'ai_anxiety_level backfill left an unmappable value: %. '
      'Map it explicitly before adding the constraint.', bad;
  end if;
end $$;

alter table career_profiles
  add constraint career_profiles_ai_anxiety_level_check
    check (
      ai_anxiety_level is null
      or ai_anxiety_level in ('low', 'moderate', 'high', 'not_sure')
    );

-- ============================================================================
-- 2. students.expected_graduation -> 'Spring YYYY' | 'Fall YYYY'
-- ============================================================================

-- The column keeps its type and its meaning but changes its FORMAT, from an
-- unlabelled 'YYYY-MM' to a term a student would recognize as their own.
--
-- NOT sourced from academic_term_dates, which was the obvious alternative and
-- is the wrong one: that table is seeded 2026-2027 (4 TAMU rows, latest
-- Summer 2027) while the values already on file are 2028-05 and 2029-05. A
-- foreign key or a dropdown fed from it could not represent a single existing
-- student's answer, let alone a freshman's. A validated string can, and the
-- picker that writes it can generate its own forward years without waiting on
-- a registrar to publish a calendar four years out.
--
-- Spring and Fall only. Institutions confer degrees at Spring and Fall
-- commencement; the Winter, May and August rows in academic_term_dates are
-- 2-3 week intersessions nobody graduates from. That restriction is also what
-- makes the backfill below unambiguous -- see the mapping note.

-- 'YYYY-05' -> 'Spring YYYY'.
--
-- Month 05 was ambiguous between Spring (TAMU's Spring 2027 ends 2027-05-11)
-- and SMU's literal 'May' intersession season, which is why this mapping
-- could not have been written before Spring/Fall-only was decided. With May
-- excluded from the target vocabulary the ambiguity is gone: 05 can only mean
-- the spring term that ends in May.
--
-- Scoped by the regex rather than by `is not null`, so a value already in the
-- new format is left untouched and this UPDATE is idempotent.

update students
set expected_graduation = 'Spring ' || substring(expected_graduation from 1 for 4)
where expected_graduation ~ '^[0-9]{4}-05$';

-- Guard: any surviving non-conforming value, including a 'YYYY-MM' with a
-- month this migration did not map. Verified to affect 0 rows today -- the
-- live data contains month 05 and nothing else -- but a database carrying a
-- '2028-12' would stop here with that value in the message rather than
-- failing anonymously at the ALTER below.
do $$
declare
  bad text;
begin
  select expected_graduation into bad
  from students
  where expected_graduation is not null
    and expected_graduation !~ '^(Spring|Fall) 20[0-9]{2}$'
  limit 1;

  if bad is not null then
    raise exception
      'expected_graduation backfill left a non-conforming value: %. '
      'Only YYYY-05 is mapped; map any other month explicitly.', bad;
  end if;
end $$;

-- 20[0-9]{2} rather than [0-9]{4}: it costs nothing and keeps a typo'd
-- 'Fall 0202' out. Matches the anchored-regex precedent set by the
-- brand_primary_hex constraints in 20260728212545.
alter table students
  add constraint students_expected_graduation_format_check
    check (
      expected_graduation is null
      or expected_graduation ~ '^(Spring|Fall) 20[0-9]{2}$'
    );

-- ============================================================================
-- 3. NOT IN THIS MIGRATION
-- ============================================================================
--
-- academic_term_dates, planned_courses and course_records are untouched. The
-- graduation picker deliberately does not read academic_term_dates (see
-- section 2), so nothing about this change requires that table to grow, and
-- extending its range remains a separate question with its own migration.

comment on column career_profiles.ai_anxiety_level is
  'How the student feels about AI in their field: low, moderate, high, or '
  'not_sure. NULL means never asked, which is distinct from not_sure. '
  'Held free text until 20260812143000, which mapped the prose values to '
  'this vocabulary.';

comment on column students.expected_graduation is
  'Anticipated graduation term as "Spring YYYY" or "Fall YYYY". Spring/Fall '
  'only -- degrees are conferred at those commencements. Deliberately a '
  'validated string and NOT a reference to academic_term_dates, whose seeded '
  'range (2026-2027) cannot express a current freshman''s answer.';
