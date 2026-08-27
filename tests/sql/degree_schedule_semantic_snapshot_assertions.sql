\set ON_ERROR_STOP on

insert into institutions(id, name) values
  ('01000000-0000-0000-0000-000000000001', 'SMU');
insert into students(id, auth_user_id, name, expected_graduation) values
  ('10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001', 'One', 'Spring 2029');
insert into programs(id, institution_id, catalog_year) values
  ('30000000-0000-0000-0000-000000000001', '01000000-0000-0000-0000-000000000001', '2026-2027');
insert into requirement_groups(id, program_id, coursedog_rule_id, name) values
  ('40000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001', 'r1', 'R1');

set role service_role;
do $$
declare
  first_result jsonb;
  same_result jsonb;
  changed_result jsonb;
  rolled_back_result jsonb;
  before_revision bigint;
begin
  select revision into before_revision from degree_schedule_institution_revisions
  where institution_id='01000000-0000-0000-0000-000000000001';
  first_result := sync_degree_schedule_institution_semantics(
    '01000000-0000-0000-0000-000000000001', 'sha256:'||repeat('a',64), '1');
  if first_result->>'status' <> 'REGISTERED'
     or (first_result->>'institution_revision')::bigint <> before_revision + 1 then
    raise exception 'first semantic registration failed';
  end if;
  same_result := sync_degree_schedule_institution_semantics(
    '01000000-0000-0000-0000-000000000001', 'sha256:'||repeat('a',64), '1');
  if same_result->>'status' <> 'UNCHANGED'
     or (same_result->>'institution_revision')::bigint <> (first_result->>'institution_revision')::bigint then
    raise exception 'same semantic identity advanced revision';
  end if;
  changed_result := sync_degree_schedule_institution_semantics(
    '01000000-0000-0000-0000-000000000001', 'sha256:'||repeat('b',64), '2');
  if changed_result->>'status' <> 'UPDATED'
     or (changed_result->>'institution_revision')::bigint <> (first_result->>'institution_revision')::bigint + 1 then
    raise exception 'changed semantic identity did not advance revision';
  end if;
  -- A still-running old instance is not silently equivalent: registering F1
  -- again advances the same checked revision and invalidates F2 snapshots.
  rolled_back_result := sync_degree_schedule_institution_semantics(
    '01000000-0000-0000-0000-000000000001', 'sha256:'||repeat('a',64), '1');
  if rolled_back_result->>'status' <> 'UPDATED'
     or (rolled_back_result->>'institution_revision')::bigint <> (changed_result->>'institution_revision')::bigint + 1 then
    raise exception 'mixed deployment did not fail closed';
  end if;
end $$;
reset role;

-- A semantic change after revision capture makes the existing CAS reject.
set role service_role;
do $$
declare snapshot jsonb; conflict jsonb;
begin
  snapshot := get_degree_schedule_revisions(
    '10000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001');
  perform sync_degree_schedule_institution_semantics(
    '01000000-0000-0000-0000-000000000001', 'sha256:'||repeat('c',64), '2');
  conflict := replace_degree_requirement_selections(
    '10000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001',
    (snapshot->>'student_revision')::bigint,
    (snapshot->>'program_revision')::bigint,
    (snapshot->>'institution_revision')::bigint,
    'sha256:'||repeat('d',64), '[]'::jsonb);
  if conflict->>'status' <> 'REVISION_CONFLICT' then
    raise exception 'stale CAS accepted after semantic synchronization';
  end if;
end $$;
reset role;

set role authenticated;
do $$ begin
  begin perform sync_degree_schedule_institution_semantics(
    '01000000-0000-0000-0000-000000000001', 'sha256:'||repeat('e',64), '1');
    raise exception 'authenticated semantic synchronization accepted';
  exception when insufficient_privilege then null; end;
  begin update degree_schedule_institution_semantics set planner_contract_version='bad';
    raise exception 'authenticated direct semantic mutation accepted';
  exception when insufficient_privilege then null; end;
end $$;
reset role;

do $$ begin
  if has_function_privilege('anon','sync_degree_schedule_institution_semantics(uuid,text,text)','EXECUTE') then raise exception 'anon can synchronize semantics'; end if;
  if has_function_privilege('authenticated','sync_degree_schedule_institution_semantics(uuid,text,text)','EXECUTE') then raise exception 'authenticated can synchronize semantics'; end if;
  if not has_function_privilege('service_role','sync_degree_schedule_institution_semantics(uuid,text,text)','EXECUTE') then raise exception 'service role cannot synchronize semantics'; end if;
end $$;
