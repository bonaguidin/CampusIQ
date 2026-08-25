\set ON_ERROR_STOP on

insert into students(id, auth_user_id) values
  ('10000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001'),
  ('10000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000002');
insert into programs(id) values
  ('30000000-0000-0000-0000-000000000001'),
  ('30000000-0000-0000-0000-000000000002');
insert into requirement_groups(id, program_id, coursedog_rule_id) values
  ('40000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001', 'rule-a'),
  ('40000000-0000-0000-0000-000000000002', '30000000-0000-0000-0000-000000000002', 'rule-b');

set role service_role;
insert into degree_requirement_selections(
  student_id, program_id, requirement_group_id, candidate_id, course_codes, decision_version
) values
  ('10000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001',
   '40000000-0000-0000-0000-000000000001', 'reqcand_a', array['CEE 2302','CS 3377'], 'sha256:' || repeat('a', 64)),
  ('10000000-0000-0000-0000-000000000002', '30000000-0000-0000-0000-000000000001',
   '40000000-0000-0000-0000-000000000001', 'reqcand_b', array['CS 4340'], 'sha256:' || repeat('b', 64));
reset role;

do $$ begin
  begin
    insert into degree_requirement_selections(student_id, program_id, requirement_group_id, candidate_id, course_codes, decision_version)
    values ('10000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001',
      '40000000-0000-0000-0000-000000000001', 'duplicate', array['CS 9999'], 'sha256:' || repeat('c', 64));
    raise exception 'duplicate active selection accepted';
  exception when unique_violation then null; end;
  begin
    insert into degree_requirement_selections(student_id, program_id, requirement_group_id, candidate_id, course_codes, decision_version)
    values ('10000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001',
      '40000000-0000-0000-0000-000000000001', 'empty', array[]::text[], 'sha256:' || repeat('d', 64));
    raise exception 'empty course path accepted';
  exception when check_violation then null; end;
  begin
    insert into degree_requirement_selections(student_id, program_id, requirement_group_id, candidate_id, course_codes, decision_version)
    values ('10000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000002',
      '40000000-0000-0000-0000-000000000001', 'wrong-program', array['CS 101'], 'sha256:' || repeat('e', 64));
    raise exception 'cross-program requirement accepted';
  exception when foreign_key_violation then null; end;
end $$;

set role authenticated;
select set_config('request.jwt.claim.sub', '20000000-0000-0000-0000-000000000001', false);
do $$ begin
  if (select count(*) from degree_requirement_selections) <> 1 then
    raise exception 'owner SELECT leaked another student or hid own row';
  end if;
  begin
    insert into degree_requirement_selections(student_id, program_id, requirement_group_id, candidate_id, course_codes, decision_version)
    values ('10000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001',
      '40000000-0000-0000-0000-000000000001', 'direct-write', array['CS 101'], 'sha256:' || repeat('f', 64));
    raise exception 'authenticated direct mutation accepted';
  exception when insufficient_privilege then null; end;
end $$;
reset role;

set role anon;
do $$ begin
  begin perform count(*) from degree_requirement_selections;
    raise exception 'anonymous read accepted';
  exception when insufficient_privilege then null; end;
end $$;
reset role;

set role service_role;
update degree_requirement_selections set updated_at = now()
where student_id = '10000000-0000-0000-0000-000000000001';
delete from degree_requirement_selections
where student_id = '10000000-0000-0000-0000-000000000002';
reset role;

