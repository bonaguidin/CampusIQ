\set ON_ERROR_STOP on

insert into institutions(id, name) values
  ('01000000-0000-0000-0000-000000000001', 'SMU'),
  ('01000000-0000-0000-0000-000000000002', 'TAMU');
insert into students(id, auth_user_id, name, expected_graduation) values
  ('10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001', 'One', 'Spring 2029'),
  ('10000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000002', 'Two', 'Spring 2029');
insert into student_institutions(id, student_id, institution_id, relationship, catalog_year) values
  ('11000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', '01000000-0000-0000-0000-000000000001', 'home', '2026-2027'),
  ('11000000-0000-0000-0000-000000000002', '10000000-0000-0000-0000-000000000002', '01000000-0000-0000-0000-000000000001', 'home', '2026-2027');
insert into programs(id, institution_id, catalog_year) values
  ('30000000-0000-0000-0000-000000000001', '01000000-0000-0000-0000-000000000001', '2026-2027');
insert into requirement_groups(id, program_id, coursedog_rule_id, name) values
  ('40000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001', 'r1', 'R1'),
  ('40000000-0000-0000-0000-000000000002', '30000000-0000-0000-0000-000000000001', 'r2', 'R2');
insert into requirement_group_options(id, requirement_group_id, option_index, logic) values
  ('41000000-0000-0000-0000-000000000001', '40000000-0000-0000-0000-000000000001', 0, 'and');
insert into requirement_group_option_courses(id, requirement_group_option_id, course_code) values
  ('42000000-0000-0000-0000-000000000001', '41000000-0000-0000-0000-000000000001', 'CEE 2302');
insert into course_catalog(id, institution_id, code, title, credit_min, coursedog_group_id) values
  ('50000000-0000-0000-0000-000000000001', '01000000-0000-0000-0000-000000000001', 'CEE 2302', 'Statics', 3, 'gid-1');
insert into academic_term_dates(id, institution_id, year, season, label, start_date, end_date) values
  ('60000000-0000-0000-0000-000000000001', '01000000-0000-0000-0000-000000000001', 2026, 'Fall', 'Fall 2026', '2026-08-24', '2026-12-15');

do $$
declare
  v jsonb;
  s bigint;
  p bigint;
  i bigint;
  before_revision bigint;
begin
  v := get_degree_schedule_revisions(
    '10000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001');
  s := (v->>'student_revision')::bigint;
  p := (v->>'program_revision')::bigint;
  i := (v->>'institution_revision')::bigint;

  insert into academic_terms(id, student_id, institution_id, year, season) values
    ('61000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', '01000000-0000-0000-0000-000000000001', 2025, 'Fall');
  insert into course_records(id, student_id, term_id, institution_id, course_code, title, credit_hours, counts_toward_credit, status) values
    ('70000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001', '61000000-0000-0000-0000-000000000001', '01000000-0000-0000-0000-000000000001', 'CS 101', 'Intro', 3, true, 'completed');
  select revision into before_revision from degree_schedule_student_revisions
  where student_id='10000000-0000-0000-0000-000000000001' and program_id='30000000-0000-0000-0000-000000000001';
  if before_revision <> s + 1 then raise exception 'course record did not bump student revision exactly once'; end if;
  update course_records set title='Display title' where id='70000000-0000-0000-0000-000000000001';
  if (select revision from degree_schedule_student_revisions where student_id='10000000-0000-0000-0000-000000000001' and program_id='30000000-0000-0000-0000-000000000001') <> before_revision then
    raise exception 'display-only course record title bumped revision';
  end if;
  update students set name='Display Name' where id='10000000-0000-0000-0000-000000000001';
  if (select revision from degree_schedule_student_revisions where student_id='10000000-0000-0000-0000-000000000001' and program_id='30000000-0000-0000-0000-000000000001') <> before_revision then
    raise exception 'irrelevant student name bumped revision';
  end if;
  update students set expected_graduation='Fall 2029' where id='10000000-0000-0000-0000-000000000001';
  if (select revision from degree_schedule_student_revisions where student_id='10000000-0000-0000-0000-000000000001' and program_id='30000000-0000-0000-0000-000000000001') <> before_revision + 1 then
    raise exception 'expected graduation did not bump student revision';
  end if;

  select revision into before_revision from degree_schedule_program_revisions where program_id='30000000-0000-0000-0000-000000000001';
  update requirement_groups set name='R1 changed' where id='40000000-0000-0000-0000-000000000001';
  if (select revision from degree_schedule_program_revisions where program_id='30000000-0000-0000-0000-000000000001') <> before_revision + 1 then
    raise exception 'requirement mutation did not bump program revision';
  end if;

  select revision into before_revision from degree_schedule_institution_revisions where institution_id='01000000-0000-0000-0000-000000000001';
  update course_catalog set title='Display only' where id='50000000-0000-0000-0000-000000000001';
  if (select revision from degree_schedule_institution_revisions where institution_id='01000000-0000-0000-0000-000000000001') <> before_revision then
    raise exception 'catalog title bumped institution revision';
  end if;
  update course_catalog set credit_min=4 where id='50000000-0000-0000-0000-000000000001';
  if (select revision from degree_schedule_institution_revisions where institution_id='01000000-0000-0000-0000-000000000001') <> before_revision + 1 then
    raise exception 'catalog credit did not bump institution revision';
  end if;
  select revision into before_revision from degree_schedule_institution_revisions where institution_id='01000000-0000-0000-0000-000000000001';
  update academic_term_dates set label='Display Fall' where id='60000000-0000-0000-0000-000000000001';
  if (select revision from degree_schedule_institution_revisions where institution_id='01000000-0000-0000-0000-000000000001') <> before_revision then
    raise exception 'calendar label bumped institution revision';
  end if;
  update academic_term_dates set start_date='2026-08-25' where id='60000000-0000-0000-0000-000000000001';
  if (select revision from degree_schedule_institution_revisions where institution_id='01000000-0000-0000-0000-000000000001') <> before_revision + 1 then
    raise exception 'calendar date did not bump institution revision';
  end if;
end $$;

set role service_role;
do $$
declare
  v jsonb;
  first_result jsonb;
  second_result jsonb;
  s bigint;
  p bigint;
  i bigint;
  original_created timestamptz;
  original_updated timestamptz;
begin
  v := get_degree_schedule_revisions('10000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001');
  s := (v->>'student_revision')::bigint; p := (v->>'program_revision')::bigint; i := (v->>'institution_revision')::bigint;
  first_result := replace_degree_requirement_selections(
    '10000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001', s, p, i,
    'sha256:' || repeat('a',64),
    '[{"requirement_group_id":"40000000-0000-0000-0000-000000000001","candidate_id":"bundle","course_codes":["CEE 2302","CS 3377"]}]'::jsonb);
  if first_result->>'status' <> 'APPLIED' or (first_result->>'student_revision')::bigint <> s + 1 then
    raise exception 'successful replacement did not apply exactly one revision';
  end if;
  if (select course_codes from degree_requirement_selections where requirement_group_id='40000000-0000-0000-0000-000000000001') <> array['CEE 2302','CS 3377'] then
    raise exception 'multi-course order not preserved';
  end if;
  select created_at, updated_at into original_created, original_updated from degree_requirement_selections
  where requirement_group_id='40000000-0000-0000-0000-000000000001';
  second_result := replace_degree_requirement_selections(
    '10000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001', s + 1, p, i,
    'sha256:' || repeat('9',64),
    '[{"requirement_group_id":"40000000-0000-0000-0000-000000000001","candidate_id":"bundle","course_codes":["CEE 2302","CS 3377"]}]'::jsonb);
  if second_result->>'status' <> 'UNCHANGED' or (second_result->>'student_revision')::bigint <> s + 1 then
    raise exception 'same-set replacement was not idempotent';
  end if;
  if exists(select 1 from degree_requirement_selections where requirement_group_id='40000000-0000-0000-0000-000000000001' and (created_at <> original_created or updated_at <> original_updated)) then
    raise exception 'idempotent replacement changed timestamps';
  end if;

  first_result := replace_degree_requirement_selections(
    '10000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001', s + 1, p, i,
    'sha256:' || repeat('b',64),
    '[{"requirement_group_id":"40000000-0000-0000-0000-000000000001","candidate_id":"one","course_codes":["CEE 2302"]},{"requirement_group_id":"40000000-0000-0000-0000-000000000002","candidate_id":"two","course_codes":["CS 4340"]}]'::jsonb);
  s := (first_result->>'student_revision')::bigint;
  second_result := replace_degree_requirement_selections(
    '10000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001', s, p, i,
    'sha256:' || repeat('c',64),
    '[{"requirement_group_id":"40000000-0000-0000-0000-000000000001","candidate_id":"three","course_codes":["CS 3377"]}]'::jsonb);
  if second_result->>'status' <> 'APPLIED' or (select count(*) from degree_requirement_selections where student_id='10000000-0000-0000-0000-000000000001') <> 1 then
    raise exception 'complete-set removal failed';
  end if;
end $$;
reset role;

-- Student academic race: mutation after snapshot rejects without changing choices.
set role service_role;
do $$
declare v jsonb; conflict jsonb; rows_before jsonb;
begin
  v := get_degree_schedule_revisions('10000000-0000-0000-0000-000000000001','30000000-0000-0000-0000-000000000001');
  select jsonb_agg(to_jsonb(s) order by requirement_group_id) into rows_before from degree_requirement_selections s;
  update course_records set status='in_progress' where id='70000000-0000-0000-0000-000000000001';
  conflict := replace_degree_requirement_selections(
    '10000000-0000-0000-0000-000000000001','30000000-0000-0000-0000-000000000001',
    (v->>'student_revision')::bigint,(v->>'program_revision')::bigint,(v->>'institution_revision')::bigint,
    'sha256:'||repeat('d',64),'[]'::jsonb);
  if conflict->>'status' <> 'REVISION_CONFLICT' then raise exception 'student race accepted'; end if;
  if (select jsonb_agg(to_jsonb(s) order by requirement_group_id) from degree_requirement_selections s) is distinct from rows_before then raise exception 'student conflict partially wrote'; end if;
end $$;
reset role;

-- Shared requirement and institution races both reject.
set role service_role;
do $$
declare v jsonb; conflict jsonb;
begin
  v := get_degree_schedule_revisions('10000000-0000-0000-0000-000000000001','30000000-0000-0000-0000-000000000001');
  update requirement_groups set name='Race' where id='40000000-0000-0000-0000-000000000002';
  conflict := replace_degree_requirement_selections('10000000-0000-0000-0000-000000000001','30000000-0000-0000-0000-000000000001',(v->>'student_revision')::bigint,(v->>'program_revision')::bigint,(v->>'institution_revision')::bigint,'sha256:'||repeat('e',64),'[]'::jsonb);
  if conflict->>'status' <> 'REVISION_CONFLICT' then raise exception 'program race accepted'; end if;
  v := get_degree_schedule_revisions('10000000-0000-0000-0000-000000000001','30000000-0000-0000-0000-000000000001');
  update course_catalog set credit_min=5 where id='50000000-0000-0000-0000-000000000001';
  conflict := replace_degree_requirement_selections('10000000-0000-0000-0000-000000000001','30000000-0000-0000-0000-000000000001',(v->>'student_revision')::bigint,(v->>'program_revision')::bigint,(v->>'institution_revision')::bigint,'sha256:'||repeat('f',64),'[]'::jsonb);
  if conflict->>'status' <> 'REVISION_CONFLICT' then raise exception 'institution race accepted'; end if;
end $$;
reset role;

-- Two tabs use one snapshot; the first wins and the stale second conflicts.
set role service_role;
do $$
declare v jsonb; first_result jsonb; second_result jsonb;
begin
  v := get_degree_schedule_revisions('10000000-0000-0000-0000-000000000001','30000000-0000-0000-0000-000000000001');
  first_result := replace_degree_requirement_selections('10000000-0000-0000-0000-000000000001','30000000-0000-0000-0000-000000000001',(v->>'student_revision')::bigint,(v->>'program_revision')::bigint,(v->>'institution_revision')::bigint,'sha256:'||repeat('1',64),'[]'::jsonb);
  second_result := replace_degree_requirement_selections('10000000-0000-0000-0000-000000000001','30000000-0000-0000-0000-000000000001',(v->>'student_revision')::bigint,(v->>'program_revision')::bigint,(v->>'institution_revision')::bigint,'sha256:'||repeat('2',64),'[{"requirement_group_id":"40000000-0000-0000-0000-000000000001","candidate_id":"late","course_codes":["CS 3377"]}]'::jsonb);
  if first_result->>'status' <> 'APPLIED' or second_result->>'status' <> 'REVISION_CONFLICT' then raise exception 'two-tab CAS failed'; end if;
end $$;
reset role;

set role authenticated;
select set_config('request.jwt.claim.sub','20000000-0000-0000-0000-000000000001',false);
do $$ begin
  if (select count(*) from degree_schedule_student_revisions) <> 1 then raise exception 'revision RLS leaked or hid row'; end if;
  begin update degree_schedule_student_revisions set revision=999;
    raise exception 'authenticated revision mutation accepted'; exception when insufficient_privilege then null; end;
  begin perform replace_degree_requirement_selections('10000000-0000-0000-0000-000000000001','30000000-0000-0000-0000-000000000001',1,1,1,'sha256:'||repeat('a',64),'[]'::jsonb);
    raise exception 'authenticated RPC invocation accepted'; exception when insufficient_privilege then null; end;
end $$;
reset role;

do $$ begin
  if has_function_privilege('anon','replace_degree_requirement_selections(uuid,uuid,bigint,bigint,bigint,text,jsonb)','EXECUTE') then raise exception 'anon can execute RPC'; end if;
  if has_function_privilege('authenticated','replace_degree_requirement_selections(uuid,uuid,bigint,bigint,bigint,text,jsonb)','EXECUTE') then raise exception 'authenticated can execute RPC'; end if;
  if not has_function_privilege('service_role','replace_degree_requirement_selections(uuid,uuid,bigint,bigint,bigint,text,jsonb)','EXECUTE') then raise exception 'service role cannot execute RPC'; end if;
end $$;
