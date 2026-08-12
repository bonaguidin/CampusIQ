-- Adds search_course_catalog(), the query behind planned-course search.
--
-- Phase 1 of term-organized Academic Record. Function only -- no table is
-- created, altered, or dropped.
--
-- ============================================================================
-- WHY A FUNCTION AND NOT A POSTGREST QUERY
-- ============================================================================
--
-- 20260804155924_course_catalog.sql built two indexes for exactly this search
-- and documented how each must be queried:
--
--   course_catalog_code_pattern_idx  on (institution_id, code text_pattern_ops)
--   course_catalog_title_pattern_idx on (institution_id, lower(title) text_pattern_ops)
--
-- and noted of the second: "the query must also use lower(title) LIKE lower(:q)
-- || '%' to hit this index; ILIKE alone will not."
--
-- PostgREST cannot express that. Its filter grammar addresses columns, not
-- expressions, so there is no way to write `lower(title) like ...` through it;
-- the closest available filter is `title=ilike.foo*`, which is a different
-- query the planner cannot answer from a lower(title) index. Wrapping the
-- query in a function is the only way to issue the one the index was built
-- for, short of adding a redundant lowercased column.
--
-- HONEST SIZING, so this is not mistaken for a performance fix: course_catalog
-- is 4,623 rows live (TAMU 1,374 + SMU 3,249). A sequential scan answers this
-- in well under a millisecond and the planner may well choose one anyway. The
-- reason to write the indexable query is that the index exists and was
-- justified in writing -- leaving it permanently unused would make the earlier
-- migration's reasoning false, and quietly so.
--
-- ============================================================================
-- MATCHING RULES
-- ============================================================================
--
-- Two prefix matches, OR'd:
--   * code  -- left-anchored, case-sensitive against the stored form. The
--     caller normalizes ("csce1" -> "CSCE 1") before calling; see
--     GradusIQ_career/planning/search.py, which reuses the same letter-run /
--     digit-run split as transcript/catalog.py's normalize_code so that
--     TAMU's "MATH 251" and SMU's "ACCT 2301" both resolve.
--   * title -- left-anchored, case-insensitive via lower() on both sides.
--
-- Both are LEFT-ANCHORED ONLY. "%machine learning%" would need pg_trgm, which
-- the course_catalog migration deliberately did not add and whose availability
-- still has not been verified against this database. A student typing "intro
-- to programming" gets nothing rather than a fuzzy match, which is the same
-- tradeoff Tier 1 catalog matching already makes for transcripts.
--
-- SECURITY INVOKER (the default, stated here rather than assumed): the
-- function runs as the caller, so course_catalog's RLS applies exactly as it
-- would to a direct read. It reads one public-read reference table and takes
-- no user identity as an argument, so there is nothing here to escalate.
-- Parameters are bound, never concatenated into SQL.

create or replace function search_course_catalog(
  p_institution_id uuid,
  p_query text,
  p_limit int default 20
)
returns table (
  id uuid,
  code text,
  title text,
  department text,
  course_level int,
  credit_min int,
  credit_max int
)
language sql
stable
as $$
  select c.id, c.code, c.title, c.department, c.course_level, c.credit_min, c.credit_max
  from course_catalog c
  where c.institution_id = p_institution_id
    and length(btrim(coalesce(p_query, ''))) > 0
    and (
      c.code like btrim(p_query) || '%'
      or lower(c.title) like lower(btrim(p_query)) || '%'
    )
  -- Shorter codes first so "MATH 25" surfaces MATH 251 ahead of MATH 251H,
  -- then alphabetically for a stable page the client can rely on.
  order by length(c.code), c.code
  limit least(greatest(coalesce(p_limit, 20), 1), 50);
$$;

comment on function search_course_catalog(uuid, text, int) is
  'Left-anchored prefix search over one institution''s course_catalog, by code '
  'or title. Exists so the lower(title) expression index built in '
  '20260804155924 can actually be used -- PostgREST cannot express a filter on '
  'an expression. Institution-scoped because (institution_id, code) is the '
  'catalog''s unique key: MATH 251 is a different course at TAMU and SMU.';

-- Matches course_catalog's own read posture: the catalog is public reference
-- data readable by anon and authenticated alike, and a pre-session course
-- search is a plausible surface.
grant execute on function search_course_catalog(uuid, text, int) to anon, authenticated;
