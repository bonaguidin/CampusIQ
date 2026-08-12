\set ON_ERROR_STOP on

do $$
declare
  function_oid oid := 'public.apply_resume_reconciliation(uuid)'::regprocedure::oid;
begin
  if has_function_privilege('anon', function_oid, 'EXECUTE') then
    raise exception 'anon should not have RPC execute';
  end if;
  if not has_function_privilege('authenticated', function_oid, 'EXECUTE') then
    raise exception 'authenticated should retain RPC execute';
  end if;
  if exists (
    select 1 from pg_proc p
    cross join lateral aclexplode(coalesce(p.proacl, acldefault('f', p.proowner))) privilege
    where p.oid = function_oid and privilege.grantee = 0
      and privilege.privilege_type = 'EXECUTE'
  ) then
    raise exception 'PUBLIC should not have RPC execute';
  end if;
end $$;

do $$
begin
  begin insert into resume_reconciliations(student_id, status)
    values ('10000000-0000-0000-0000-000000000001', 'bad');
    raise exception 'invalid status accepted'; exception when check_violation then null; end;
  begin insert into resume_reconciliation_items(
    reconciliation_id, student_id, domain, classification, proposed_value)
    values ('30000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001',
      'bad', 'add', '{}');
    raise exception 'invalid domain accepted'; exception when check_violation then null; end;
  begin insert into resume_reconciliation_items(
    reconciliation_id, student_id, domain, classification, proposed_value)
    values ('30000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001',
      'project', 'bad', '{}');
    raise exception 'invalid classification accepted'; exception when check_violation then null; end;
  begin insert into resume_reconciliation_items(
    reconciliation_id, student_id, domain, classification, proposed_value, decision)
    values ('30000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001',
      'project', 'add', '{}', 'bad');
    raise exception 'invalid decision accepted'; exception when check_violation then null; end;
  begin insert into resume_reconciliations(id, student_id, status)
    values ('30000000-0000-0000-0000-000000000099', '10000000-0000-0000-0000-000000000001', 'pending');
    raise exception 'second pending reconciliation accepted'; exception when unique_violation then null; end;
  begin insert into resume_reconciliation_items(
    reconciliation_id, student_id, domain, classification, proposed_value)
    values ('30000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000002',
      'project', 'add', '{}');
    raise exception 'cross-student item accepted'; exception when foreign_key_violation then null; end;
end $$;

set role authenticated;
select set_config('request.jwt.claim.sub', '20000000-0000-0000-0000-000000000001', false);
do $$ begin
  if (select count(*) from resume_reconciliations) <> 1 then
    raise exception 'own reconciliation not visible or foreign reconciliation leaked';
  end if;
  if (select count(*) from resume_reconciliation_items) <> 3 then
    raise exception 'own items not visible or foreign items leaked';
  end if;
  begin
    insert into resume_reconciliations(student_id, status)
    values ('10000000-0000-0000-0000-000000000002', 'discarded');
    raise exception 'cross-student reconciliation insert accepted';
  exception when insufficient_privilege then null; end;
end $$;

do $$ begin
  begin perform apply_resume_reconciliation('30000000-0000-0000-0000-000000000002');
    raise exception 'another student reconciliation was accessible';
  exception when raise_exception then
    if sqlerrm <> 'RECONCILIATION_NOT_FOUND' then raise; end if;
  end;
end $$;

insert into resume_reconciliation_items(
  reconciliation_id, student_id, domain, classification, canonical_row_id,
  canonical_row_updated_at, proposed_value
) values (
  '30000000-0000-0000-0000-000000000001',
  '10000000-0000-0000-0000-000000000001',
  'project', 'possible_match',
  '50000000-0000-0000-0000-000000000001', '2026-01-01Z', '{}'
);
do $$ begin
  begin perform apply_resume_reconciliation('30000000-0000-0000-0000-000000000001');
    raise exception 'unresolved possible match was applied';
  exception when raise_exception then
    if sqlerrm <> 'RECONCILIATION_UNRESOLVED_MATCH' then raise; end if;
  end;
end $$;
update resume_reconciliation_items
set decision = 'keep'
where reconciliation_id = '30000000-0000-0000-0000-000000000001'
  and classification = 'possible_match';

select apply_resume_reconciliation('30000000-0000-0000-0000-000000000001');
reset role;

do $$ begin
  if (select major_current from students where id='10000000-0000-0000-0000-000000000001') <> 'Computer Engineering' then raise exception 'major not applied'; end if;
  if (select expected_graduation from students where id='10000000-0000-0000-0000-000000000001') <> 'Spring 2029' then raise exception 'graduation not applied'; end if;
  if (select major_intended from students where id='10000000-0000-0000-0000-000000000001') <> 'N/A' then raise exception 'intended major changed'; end if;
  if (select skills_technical from career_profiles where student_id='10000000-0000-0000-0000-000000000001') <> array['Python','React','Docker','PyTorch'] then raise exception 'skills not additively merged'; end if;
  if (select target_roles from career_profiles where student_id='10000000-0000-0000-0000-000000000001') <> array['Engineer'] then raise exception 'target roles changed'; end if;
  if (select interests from career_profiles where student_id='10000000-0000-0000-0000-000000000001') <> array['Robotics'] then raise exception 'interests changed'; end if;
  if (select ai_anxiety_level from career_profiles where student_id='10000000-0000-0000-0000-000000000001') <> 'low' then raise exception 'AI anxiety changed'; end if;
  if (select duration from work_experience where id='40000000-0000-0000-0000-000000000001') <> 'Jun 2026 - Aug 2026' then raise exception 'experience not updated'; end if;
  if (select source from work_experience where id='40000000-0000-0000-0000-000000000001') <> 'resume_parse' then raise exception 'provenance changed'; end if;
  -- Seeded confirmed_at is 2026-01-01Z, so "not null" cannot detect a dropped
  -- refresh the way it can on the rows inserted below. profile_builder.py drops
  -- the whole career block when this is null, and a stale stamp is the same
  -- class of failure, so the assertion is that applying MOVED it.
  if (select confirmed_at from career_profiles where student_id='10000000-0000-0000-0000-000000000001') <= '2026-01-01Z'::timestamptz then raise exception 'career profile confirmation not refreshed'; end if;
  if not exists(select 1 from projects where name='SAFE-AGENT' and source='resume_parse' and confirmed_at is not null) then raise exception 'project not added'; end if;
  if not exists(select 1 from certifications where name='NVIDIA Associate' and source='resume_parse' and confirmed_at is not null) then raise exception 'certification not added'; end if;
  if (select status from resume_reconciliations where id='30000000-0000-0000-0000-000000000001') <> 'applied' then raise exception 'reconciliation not applied'; end if;
end $$;

set role authenticated;
select set_config('request.jwt.claim.sub', '20000000-0000-0000-0000-000000000001', false);
do $$ begin
  begin perform apply_resume_reconciliation('30000000-0000-0000-0000-000000000001');
    raise exception 'double apply accepted';
  exception when raise_exception then
    if sqlerrm <> 'RECONCILIATION_NOT_PENDING' then raise; end if;
  end;
end $$;
reset role;

-- Stale student, career profile, and each child domain are rejected.
do $$
declare rid uuid; item_id uuid; baseline timestamptz;
begin
  select updated_at into baseline from students where id='10000000-0000-0000-0000-000000000001';
  insert into resume_reconciliations(student_id,status,base_student_updated_at,base_career_profile_updated_at)
  select id,'pending',baseline,(select updated_at from career_profiles where student_id=students.id)
  from students where id='10000000-0000-0000-0000-000000000001' returning id into rid;
  update students set updated_at=updated_at + interval '1 second' where id='10000000-0000-0000-0000-000000000001';
  perform set_config('request.jwt.claim.sub', '20000000-0000-0000-0000-000000000001', false);
  set local role authenticated;
  begin perform apply_resume_reconciliation(rid); exception when raise_exception then
    if sqlerrm <> 'RECONCILIATION_STALE' then raise; end if; end;
  reset role;
  update resume_reconciliations set status='discarded' where id=rid;

  update students set updated_at=baseline where id='10000000-0000-0000-0000-000000000001';
  insert into resume_reconciliations(student_id,status,base_student_updated_at,base_career_profile_updated_at)
  select id,'pending',updated_at,(select updated_at from career_profiles where student_id=students.id)
  from students where id='10000000-0000-0000-0000-000000000001' returning id into rid;
  update career_profiles set updated_at=updated_at + interval '1 second' where student_id='10000000-0000-0000-0000-000000000001';
  set local role authenticated;
  begin perform apply_resume_reconciliation(rid); exception when raise_exception then
    if sqlerrm <> 'RECONCILIATION_STALE' then raise; end if; end;
  reset role;
  update resume_reconciliations set status='discarded' where id=rid;

  foreach item_id in array array[
    '40000000-0000-0000-0000-000000000001'::uuid,
    '50000000-0000-0000-0000-000000000001'::uuid,
    '60000000-0000-0000-0000-000000000001'::uuid
  ] loop
    update career_profiles set updated_at=clock_timestamp() where student_id='10000000-0000-0000-0000-000000000001';
    insert into resume_reconciliations(student_id,status,base_student_updated_at,base_career_profile_updated_at)
    select id,'pending',updated_at,(select updated_at from career_profiles where student_id=students.id)
    from students where id='10000000-0000-0000-0000-000000000001' returning id into rid;
    insert into resume_reconciliation_items(reconciliation_id,student_id,domain,classification,canonical_row_id,canonical_row_updated_at,proposed_value,decision)
    select rid,'10000000-0000-0000-0000-000000000001',
      case when item_id::text like '4%' then 'work_experience' when item_id::text like '5%' then 'project' else 'certification' end,
      'update',item_id,
      case when item_id::text like '4%' then (select updated_at from work_experience where id=item_id)
           when item_id::text like '5%' then (select updated_at from projects where id=item_id)
           else (select updated_at from certifications where id=item_id) end,
      '{}','accept';
    if item_id::text like '4%' then update work_experience set updated_at=updated_at+interval '1 second' where id=item_id;
    elsif item_id::text like '5%' then update projects set updated_at=updated_at+interval '1 second' where id=item_id;
    else update certifications set updated_at=updated_at+interval '1 second' where id=item_id; end if;
    set local role authenticated;
    begin perform apply_resume_reconciliation(rid); exception when raise_exception then
      if sqlerrm <> 'RECONCILIATION_STALE' then raise; end if; end;
    reset role;
    update resume_reconciliations set status='discarded' where id=rid;
  end loop;
end $$;

-- Atomicity: the academic update precedes this invalid certification insert,
-- but the constraint failure rolls the entire function call back.
do $$ declare rid uuid; before_major text; begin
  select major_current into before_major from students where id='10000000-0000-0000-0000-000000000001';
  update career_profiles set updated_at=clock_timestamp() where student_id='10000000-0000-0000-0000-000000000001';
  insert into resume_reconciliations(student_id,status,academic_proposal,base_student_updated_at,base_career_profile_updated_at)
  select id,'pending','{"major_current":{"value":"Should Roll Back","decision":"accept"}}',updated_at,
    (select updated_at from career_profiles where student_id=students.id)
  from students where id='10000000-0000-0000-0000-000000000001' returning id into rid;
  insert into resume_reconciliation_items(reconciliation_id,student_id,domain,classification,proposed_value,decision)
  values(rid,'10000000-0000-0000-0000-000000000001','certification','add',
    '{"name":"Invalid Cert","status":"expired"}','accept');
  perform set_config('request.jwt.claim.sub', '20000000-0000-0000-0000-000000000001', false);
  set local role authenticated;
  begin perform apply_resume_reconciliation(rid); exception when check_violation then null; end;
  reset role;
  if (select major_current from students where id='10000000-0000-0000-0000-000000000001') <> before_major then raise exception 'atomic rollback failed'; end if;
  if (select status from resume_reconciliations where id=rid) <> 'pending' then raise exception 'failed reconciliation not pending'; end if;
end $$;
