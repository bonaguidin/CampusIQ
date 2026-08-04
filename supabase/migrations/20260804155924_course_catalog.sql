-- Adds course_catalog (institution-wide course reference data) and a
-- nullable course_records.catalog_course_id pointing at it.
--
-- Not applied. DDL only. No import script, no endpoint.
--
-- ============================================================================
-- VERIFICATION (2026-08-04, read-only against the live linked database,
-- run immediately before writing this file)
-- ============================================================================
--
-- 1. No table named course_catalog exists. PostgREST:
--      GET /rest/v1/course_catalog -> HTTP 404
--      {"code":"PGRST205","message":"Could not find the table
--       'public.course_catalog' in the schema cache"}
--    The exposed public schema is exactly 10 tables -- academic_terms,
--    career_profiles, certifications, course_records, grade_point_map,
--    institutions, projects, student_institutions, students,
--    work_experience -- matching the 10 `create table` statements across
--    the 7 prior migrations. No view or materialized view exists at all,
--    so there is no collision on the name from any object type.
--
-- 2. No column named catalog_course_id exists on course_records:
--      GET /rest/v1/course_records?select=catalog_course_id -> HTTP 400
--      {"code":"42703","message":"column course_records.catalog_course_id
--       does not exist"}
--    Live course_records is exactly 19 columns: id, student_id, term_id,
--    institution_id, course_code, title, credit_hours, letter_grade,
--    credit_type, counts_toward_credit, counts_toward_gpa, status, source,
--    exam_source, exam_score, confirmed_at, created_at, updated_at,
--    excluded_from_gpa_by. No drift from the migration history.
--
-- 3. Existing public-read policy shape, to match naming and definition
--    exactly (20260729032307_institutions_anon_read.sql:38-48):
--
--      create policy institutions_read_public
--        on institutions for select
--        to anon, authenticated
--        using (true);
--
--      create policy grade_point_map_read_public
--        on grade_point_map for select
--        to anon, authenticated
--        using (true);
--
--    Confirmed live-effective behaviorally: anon SELECT returns 200 with
--    rows on both institutions and grade_point_map, while anon SELECT on
--    course_records returns 200 with `[]` (RLS default-deny, no anon
--    policy). The policy below copies that shape verbatim -- SELECT only,
--    to anon and authenticated, USING (true), named <table>_read_public.
--
-- 4. The additive column is safe for the one existing INSERT path.
--    scripts/import_students.py is the only writer to course_records
--    (CampusIQ_career/api.py:689 and import_students_dryrun.py are
--    read-only; the frontend writes only students and
--    student_institutions). Verified rather than assumed: the importer
--    builds a 10-key dict at import_students.py:308-319 and hands it to
--    plan_upsert(), which at line 86/91 calls
--    `client.table(table).update(desired)` / `.insert(payload)` with that
--    dict. It never enumerates a column list, never issues positional
--    INSERT, and never does select-then-reinsert of a fixed column set.
--    A new nullable column with no default is therefore invisible to it.
--    One knock-on effect worth stating: api.py:689 does `select("*")` on
--    course_records, so catalog_course_id will begin appearing (as null)
--    in that response payload once this is applied.
--
-- ============================================================================
-- Data shape backing the constraints below (audited across all 19 catalog
-- JSON files, 1,374 entries, data/catalog/):
--   - credit_min spans 0-6, credit_max spans 0-23, integers throughout --
--     zero fractional values anywhere, unlike course_records.credit_hours
--     which is numeric(4,2). int is sufficient here.
--   - All 1,374 rows satisfy credit_max >= credit_min, including the 105
--     rows where credit_min = 0 (zero-credit lower bound on variable-credit
--     research/internship courses), so the check constraint below admits
--     every existing row.
--   - credit_min = credit_max on 1,216 rows (88.5%); they differ on 158
--     (11.5%). Storing the pair rather than a single credit_hours is what
--     lets those 158 survive: in the source JSON they are range *strings*
--     ("1-4", "0-23"), a second type in the same field. The pair is
--     lossless and needs no coercion.
--   - code is unique within the 1,374 rows, but only because this is a
--     single-institution snapshot -- SMU has its own MATH 251. Hence the
--     unique key is (institution_id, code), never code alone.
--   - course_level is null on 87 rows (86 x 6xx, 1 x 7xx graduate courses
--     that the 100-400 normalizer does not map), so it must stay nullable.
--   - prerequisites is null on 130 rows; description and department are
--     populated on all 1,374, so both are NOT NULL.
-- ============================================================================


-- ============================================================================
-- 1. course_catalog
-- ============================================================================

create table course_catalog (
  id uuid primary key default gen_random_uuid(),
  institution_id uuid not null references institutions (id),
  code text not null,
  prefix text not null,
  number text not null,
  title text not null,
  description text not null,
  department text not null,
  course_level int null,
  credit_min int not null,
  credit_max int not null,
  prerequisites text null,
  catalog_year text not null,
  source_last_checked date not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (institution_id, code),
  constraint course_catalog_credit_range
    check (credit_min >= 0 and credit_max >= credit_min)
);

comment on table course_catalog is
  'Institution-wide reference data: the courses an institution offers. '
  'Distinct from course_records, which is one specific student''s enrollment '
  'history. A row here is "MATH 251 exists at TAMU and is worth 3 credits"; a '
  'row in course_records is "this student took MATH 251 in Fall 2025 and got a '
  'B". catalog_year and source_last_checked are stored per-row rather than in a '
  'separate import-batch table -- deliberately simple for v1, since nothing '
  'currently needs multiple catalog years to coexist. Revisit only if a feature '
  'requires querying across scrape versions.';

comment on column course_catalog.code is
  'Full course code, e.g. "MATH 251". Unique per institution, not globally -- '
  'MATH 251 exists at both TAMU and SMU as different courses.';

comment on column course_catalog.course_level is
  'Derived from the leading digit of number: 100/200/300/400. Null for '
  'graduate-level courses (6xx, 7xx), which the normalizer does not map -- 87 '
  'of the 1,374 TAMU rows.';

comment on column course_catalog.credit_min is
  'Lower bound of credit value. Equals credit_max for fixed-credit courses '
  '(88.5% of rows). May be 0 for variable-credit research and internship '
  'courses.';

comment on column course_catalog.credit_max is
  'Upper bound of credit value. Differs from credit_min only for '
  'variable-credit courses, e.g. "1-4" directed studies.';

comment on column course_catalog.prerequisites is
  'Original prerequisite text as published, for display only. Not parsed and '
  'not enforced. Null when the source lists none.';

comment on column course_catalog.catalog_year is
  'Academic year of the source catalog, e.g. "2026-2027". Per-row by design; '
  'see the table comment.';

comment on column course_catalog.source_last_checked is
  'Date the source catalog was last fetched. Per-row by design; see the table '
  'comment.';


-- ============================================================================
-- 2. course_records.catalog_course_id
-- ============================================================================

alter table course_records
  add column catalog_course_id uuid null references course_catalog (id);

comment on column course_records.catalog_course_id is
  'Set when a student selects a course from catalog search. Null for free-text '
  'manual entries, for transcript-parsed rows the catalog could not match, and '
  'for every row that predates the catalog. Nullable and unenforced by design: '
  'a student may legitimately record a course this catalog does not carry, and '
  'course_records.course_code remains the authoritative value for GPA and '
  'credit math either way.';


-- ============================================================================
-- 3. Row level security
-- ============================================================================

-- Same posture as the other reference tables: RLS enabled, exactly one
-- permissive SELECT policy for anon + authenticated, and no write policy for
-- any role. PostgreSQL default-denies any command with no permissive policy,
-- so INSERT/UPDATE/DELETE are blocked for anon and authenticated alike.
-- Writes happen only through the import script running under the secret key,
-- which bypasses RLS as the service role.
--
-- Anon read is intentional and matches institutions/grade_point_map: course
-- catalog data is public information published on a registrar's website, and
-- a pre-session course search is a plausible surface.

alter table course_catalog enable row level security;

create policy course_catalog_read_public
  on course_catalog for select
  to anon, authenticated
  using (true);

-- Companion to 20260801175516_revoke_anon_writes_on_reference_tables.sql,
-- which found anon holding the Supabase default
-- `GRANT ALL ON ALL TABLES IN SCHEMA public` on the two existing reference
-- tables and stripped the write grants. That default grant applies to newly
-- created tables in this schema as well, so course_catalog needs the same
-- treatment on creation rather than as a later cleanup. SELECT is deliberately
-- NOT revoked -- the public-read policy above depends on it. REFERENCES and
-- TRIGGER are left alone, consistent with that migration: neither permits data
-- modification.

revoke insert, update, delete, truncate on course_catalog from anon;


-- ============================================================================
-- 4. Indexes
-- ============================================================================

-- Sizing note, so the reasoning below is read in context: the TAMU catalog is
-- 1,374 rows / ~1.5 MB. At that size PostgreSQL will seq-scan in well under a
-- millisecond and may ignore these indexes entirely. They are here so the
-- access patterns are declared correctly from the start, not because anything
-- is slow today. That is also why this stops well short of full-text search.

-- Exact code lookup ("MATH 251") and the institution_id scoping every query
-- will carry are already served by the unique (institution_id, code)
-- constraint's implicit btree. No separate index is added for that.

-- Prefix-anchored matching needs operator-class indexes: a default-collation
-- btree cannot serve LIKE 'foo%' outside the C locale. Both indexes below use
-- text_pattern_ops for that reason.

-- Subject-code autocomplete: "CSCE 1" -> CSCE 110, CSCE 120, ...
create index course_catalog_code_pattern_idx
  on course_catalog (institution_id, code text_pattern_ops);

-- Title search. Case-insensitive via lower(), so the query must also use
-- lower(title) LIKE lower(:q) || '%' to hit this index; ILIKE alone will not.
-- Left-anchored prefix match only -- an infix search ("%machine learning%")
-- still scans.
create index course_catalog_title_pattern_idx
  on course_catalog (institution_id, lower(title) text_pattern_ops);

-- Deliberately NOT doing full-text search (tsvector + GIN) in v1. It costs a
-- generated column, a trigger or generated-always expression to keep it
-- current, and a stemming configuration decision -- for a corpus where a
-- sequential scan is already fast.
--
-- pg_trgm would be the natural next step for genuine fuzzy/infix matching
-- ("intro to programing" -> "Programming I"), and this project already
-- establishes the `create extension if not exists` pattern with pgcrypto at
-- 20260728000103:8. It is NOT used here because its availability could not be
-- verified against the live database from this session -- PostgREST exposes no
-- way to read pg_available_extensions, and enabling an unverified extension is
-- not something to do blind inside a migration. The btree/text_pattern_ops
-- approach needs no extension and cannot fail to apply.
--
-- The concrete trigger for revisiting: title prefix matching is weakest
-- exactly where the corpus is most repetitive. "Directed Studies" is the title
-- of 46 distinct courses, "Special Topics in..." 44, and "Research" 38 -- a
-- prefix query for any of those returns dozens of rows that only the code
-- distinguishes. If title search becomes a primary surface rather than a
-- fallback behind code search, pg_trgm (verified available first) is the fix.
