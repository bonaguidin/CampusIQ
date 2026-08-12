-- Adds academic_term_dates: institution-wide academic calendar data (when a
-- term starts and ends), plus the TAMU 2026-2027 seed.
--
-- Phase 1 of term-organized Academic Record. DDL and seeds only.
--
-- ============================================================================
-- VERIFICATION (2026-08-11, read-only against the live linked database,
-- run immediately before writing this file)
-- ============================================================================
--
-- 1. No table named academic_term_dates exists:
--      GET /rest/v1/academic_term_dates -> HTTP 404 (PGRST205)
--
-- 2. academic_terms carries NO date columns. Probed individually, because a
--    missing column is the only thing PostgREST reports precisely:
--      GET /rest/v1/academic_terms?select=start_date -> HTTP 400
--      {"code":"42703","message":"column academic_terms.start_date
--       does not exist"}
--    Same for end_date. Live academic_terms is exactly the 8 columns the
--    original schema declared: id, student_id, institution_id, label, year,
--    season, sequence, created_at.
--
-- 3. institutions has no calendar column either:
--      GET /rest/v1/institutions?select=academic_calendar_url -> 42703
--
-- ============================================================================
-- WHY A SEPARATE TABLE AND NOT COLUMNS ON academic_terms
-- ============================================================================
--
-- academic_terms rows are PER STUDENT: five different students each own their
-- own "Fall 2026" row (verified live -- 8 rows, 5 of them one-per-student
-- placeholders). Term dates are a property of the INSTITUTION's calendar, not
-- of any student's enrollment. Putting start_date on academic_terms would
-- store TAMU's Fall 2026 start date once per student who has that term, with
-- nothing keeping the copies in agreement, and would leave no place at all to
-- record a term the student has not enrolled in yet -- which is precisely the
-- term this feature exists to let them plan.
--
-- So the join key is (institution_id, year, season), which is the same
-- identity terms.py already treats as a term's real identity when it reuses
-- academic_terms rows. The label is deliberately NOT part of the key: "Fall
-- 2026 - College Station" and "Fall 2026" are one term, and terms.py has
-- resolved that to (year, season) since the beginning.
--
-- ============================================================================
-- SEASON VOCABULARY
-- ============================================================================
--
-- season is text with a CHECK constraint here, unlike academic_terms.season
-- which has none (re-verified live 2026-08-11: an insert carrying
-- season='NotASeason' fails only on the student_id foreign key, proving no
-- season constraint rejected it first). The difference is deliberate and is
-- not an oversight on either side:
--
--   * academic_terms.season is written from parsed transcript text, whose
--     vocabulary is whatever a registrar printed. Constraining it would turn
--     an unusual heading into a failed upload. terms.py normalizes instead.
--   * academic_term_dates.season is written only by this migration and by
--     scripts/fetch_smu_term_dates.py, both of which emit the canonical
--     vocabulary. A typo here would silently orphan a whole institution's
--     calendar from the terms it is supposed to date, and nothing downstream
--     would report it -- the join would just return no rows.
--
-- The six values match SEASON_ORDER in GradusIQ_career/transcript/terms.py.
-- 'May' and 'August' are SMU intersession terms and are first-class seasons
-- rather than being folded into Summer/Fall: SMU's own calendar runs May 2026
-- (May 16 - Jun 2) and Summer 2026 (Jun 3 - Aug 4) as separate terms with
-- separate registration, so folding them would collide two distinct terms onto
-- one (institution_id, year, season) key.

create table academic_term_dates (
  id uuid primary key default gen_random_uuid(),
  institution_id uuid not null references institutions (id),
  year int not null,
  season text not null,
  label text not null,
  start_date date not null,
  end_date date not null,
  source text not null check (source in ('registrar_published', 'coursedog')),
  source_last_checked date not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (institution_id, year, season),
  constraint academic_term_dates_season_check
    check (season in ('Winter', 'Spring', 'May', 'Summer', 'August', 'Fall')),
  constraint academic_term_dates_date_range
    check (end_date >= start_date)
);

comment on table academic_term_dates is
  'Institution academic calendar: when each term starts and ends. Joined to '
  'the per-student academic_terms rows on (institution_id, year, season) -- '
  'never on label, which is free text as printed by a registrar. A row here '
  'may exist for a term no student has enrolled in yet; that is the point, '
  'since planning a future term requires knowing when it starts.';

comment on column academic_term_dates.year is
  'CALENDAR year of the term, matching academic_terms.year and what '
  'terms.parse_term_label derives. NOT the academic/fiscal year. This '
  'distinction bites on the Coursedog import: its terms carry year="2026" for '
  'Fall 2025, so scripts/fetch_smu_term_dates.py derives the year by parsing '
  'displayName and never reads Coursedog''s own year field.';

comment on column academic_term_dates.label is
  'Display label for the term as its own institution names it, e.g. '
  '"August 2026" at SMU. Not a key -- see the table comment.';

comment on column academic_term_dates.start_date is
  'First day of classes. Chosen over the registration-opens or move-in date '
  'because "has the term started?" is what the upcoming-term detection asks.';

comment on column academic_term_dates.end_date is
  'Last day of final examinations, not the last day of classes. The term is '
  'not over while exams are still being written, and grades -- the thing that '
  'eventually turns a planned course into a course_record -- do not exist '
  'until after them.';

comment on column academic_term_dates.source is
  '''registrar_published'' for dates transcribed from an institution''s own '
  'published calendar (TAMU, seeded below). ''coursedog'' for the SMU '
  'snapshot. Recorded per row so a wrong date can be traced to the thing that '
  'supplied it.';

comment on column academic_term_dates.source_last_checked is
  'Date the source was last read. Mirrors course_catalog.source_last_checked, '
  'including its per-row-by-design tradeoff: no separate import-batch table.';


-- ============================================================================
-- Row level security
-- ============================================================================

-- Same posture as institutions, grade_point_map and course_catalog: RLS on,
-- exactly one permissive SELECT policy for anon + authenticated, no write
-- policy for any role. An academic calendar is public information published on
-- a registrar's website, and the term dropdown needs to read it before a
-- student has done anything. Writes happen only through the seed below and the
-- fetch script running under the secret key, which bypasses RLS as the service
-- role.

alter table academic_term_dates enable row level security;

create policy academic_term_dates_read_public
  on academic_term_dates for select
  to anon, authenticated
  using (true);

-- Companion to 20260801175516_revoke_anon_writes_on_reference_tables.sql: the
-- Supabase default `GRANT ALL ON ALL TABLES IN SCHEMA public` applies to newly
-- created tables too, so the write grants are stripped on creation rather than
-- as a later cleanup. SELECT is deliberately NOT revoked -- the policy above
-- depends on it.

revoke insert, update, delete, truncate on academic_term_dates from anon;


-- ============================================================================
-- Index
-- ============================================================================

-- The two access patterns are "this institution's terms, in date order" (the
-- dropdown) and "this institution's next term after today" (the upcoming-term
-- default). Both are institution-scoped and ordered by start_date, and the
-- unique (institution_id, year, season) btree serves neither -- (year, season)
-- does not sort chronologically, since season is text where 'August' < 'Fall'
-- < 'May' alphabetically but not calendrically.
--
-- Sizing note, matching course_catalog's: this table holds tens of rows. A
-- seq-scan is faster than the index. It exists to declare the access pattern.

create index academic_term_dates_institution_start_idx
  on academic_term_dates (institution_id, start_date);


-- ============================================================================
-- TAMU seed: 2026-2027 academic year
-- ============================================================================
--
-- SOURCE: Texas A&M University and Texas A&M University at Galveston
-- "University Academic Calendars", the official calendar PDF published at
--   https://catalog.tamu.edu/undergraduate/academic-calendar/academic-calendar.pdf
-- (linked from https://catalog.tamu.edu/undergraduate/academic-calendar/).
-- Retrieved and transcribed 2026-08-11. Every date below was read from the
-- PDF's own text, not from a search-result summary -- an intermediate summary
-- of this same document reported Spring 2027 classes beginning January 11,
-- which the PDF contradicts ("January 19 Tuesday. First day of spring semester
-- classes."). The PDF header carries "All dates and times are subject to
-- change", hence source_last_checked.
--
-- start_date = first day of classes. end_date = last day of final exams.
--
-- VERBATIM ROWS BEHIND EACH VALUE:
--
--   Summer 2026 (10-week semester -- see the note below on which summer)
--     "May 26 Tuesday. First day of 10-week classes."
--     "August 5-6 Wednesday - Thursday. 10-week final examinations for all
--      students."                                    -> 2026-05-26 / 2026-08-06
--
--   Fall 2026
--     "August 24 Monday. First day of fall semester classes."
--     "December 7-10 Monday-Thursday. Fall semester final examinations for all
--      students."                                    -> 2026-08-24 / 2026-12-10
--
--   Spring 2027
--     "January 19 Tuesday. First day of spring semester classes."
--     "May 6-7, 10-11 Thursday-Friday, Monday-Tuesday. Spring semester final
--      examinations for all students."               -> 2027-01-19 / 2027-05-11
--
--   Summer 2027 (10-week semester)
--     "June 1 Tuesday. First day of 10-week classes."
--     "August 10-11 Wednesday - Thursday. 10-week final examinations for all
--      students."                                    -> 2027-06-01 / 2027-08-11
--
-- WHICH SUMMER. TAMU runs three overlapping summer terms -- Summer Term I,
-- Summer Term II, and the 10-week Summer Semester. This schema has exactly one
-- (institution_id, year, 'Summer') slot, so one had to be chosen. The 10-week
-- semester is the enclosing one: it starts with Term I and ends with Term II
-- (2026: 10-week May 26 - Aug 6; Term I May 26 - Jun 30; Term II Jul 6 -
-- Aug 11 per the second-term rows). Choosing it means "is the summer term
-- underway?" is true for a student in any of the three, which is the question
-- the dropdown asks. A student enrolled specifically in Term II sees a start
-- date earlier than their own first class; that is the accepted cost of one
-- summer slot, and it is recorded here rather than discovered later.
--
-- NOT SEEDED: Fall 2025 and Spring 2026, which two live academic_terms rows
-- reference. They predate this calendar PDF and are outside the 2026-2027
-- scope. The frontend renders a term with no dates row as a plain label with
-- no date line, so those terms still appear in the dropdown -- they just do
-- not participate in upcoming-term detection, which only ever looks forward.

insert into academic_term_dates
  (institution_id, year, season, label, start_date, end_date, source, source_last_checked)
select
  institutions.id, v.year, v.season, v.label, v.start_date, v.end_date,
  'registrar_published', date '2026-08-11'
from institutions
cross join (values
  (2026, 'Summer', 'Summer 2026', date '2026-05-26', date '2026-08-06'),
  (2026, 'Fall',   'Fall 2026',   date '2026-08-24', date '2026-12-10'),
  (2027, 'Spring', 'Spring 2027', date '2027-01-19', date '2027-05-11'),
  (2027, 'Summer', 'Summer 2027', date '2027-06-01', date '2027-08-11')
) as v(year, season, label, start_date, end_date)
where institutions.name = 'Texas A&M University';
