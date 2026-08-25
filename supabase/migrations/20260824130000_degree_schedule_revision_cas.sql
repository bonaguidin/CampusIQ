-- Transactional freshness guards for future Degree Schedule choice writes.
-- schedule_version remains the semantic client fingerprint; these monotonic
-- revisions only prove that database-backed validation inputs did not change
-- between Python reconstruction and this transaction.

create table degree_schedule_student_revisions (
  student_id uuid not null references students(id) on delete cascade,
  program_id uuid not null references programs(id) on delete cascade,
  revision bigint not null default 1 check (revision > 0),
  updated_at timestamptz not null default now(),
  primary key (student_id, program_id)
);

create table degree_schedule_program_revisions (
  program_id uuid primary key references programs(id) on delete cascade,
  revision bigint not null default 1 check (revision > 0),
  updated_at timestamptz not null default now()
);

create table degree_schedule_institution_revisions (
  institution_id uuid primary key references institutions(id) on delete cascade,
  revision bigint not null default 1 check (revision > 0),
  updated_at timestamptz not null default now()
);

alter table degree_schedule_student_revisions enable row level security;
alter table degree_schedule_program_revisions enable row level security;
alter table degree_schedule_institution_revisions enable row level security;

create policy degree_schedule_student_revisions_owner_select
  on degree_schedule_student_revisions for select to authenticated
  using (exists (
    select 1 from students s
    where s.id = degree_schedule_student_revisions.student_id
      and s.auth_user_id = auth.uid()
  ));

revoke all on degree_schedule_student_revisions from anon, authenticated;
revoke all on degree_schedule_program_revisions from anon, authenticated;
revoke all on degree_schedule_institution_revisions from anon, authenticated;
grant select on degree_schedule_student_revisions to authenticated;
grant all on degree_schedule_student_revisions to service_role;
grant all on degree_schedule_program_revisions to service_role;
grant all on degree_schedule_institution_revisions to service_role;

create or replace function degree_schedule_bump_student_revision()
returns trigger
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  v_student_id uuid := case when tg_op = 'DELETE' then old.student_id else new.student_id end;
begin
  if current_setting('app.degree_schedule_revision_bump_suppressed', true) = 'on' then
    return coalesce(new, old);
  end if;
  update public.degree_schedule_student_revisions
  set revision = revision + 1, updated_at = clock_timestamp()
  where student_id = v_student_id;
  if tg_op = 'UPDATE' and old.student_id is distinct from new.student_id then
    update public.degree_schedule_student_revisions
    set revision = revision + 1, updated_at = clock_timestamp()
    where student_id = old.student_id;
  end if;
  return coalesce(new, old);
end $$;

create trigger degree_schedule_course_records_revision
after insert or delete or update of student_id, term_id, institution_id, course_code,
  credit_hours, counts_toward_credit, status, catalog_course_id
on course_records for each row execute function degree_schedule_bump_student_revision();

create trigger degree_schedule_selections_revision
after insert or update or delete on degree_requirement_selections
for each row execute function degree_schedule_bump_student_revision();

create or replace function degree_schedule_bump_student_profile_revision()
returns trigger
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
begin
  update public.degree_schedule_student_revisions
  set revision = revision + 1, updated_at = clock_timestamp()
  where student_id = new.id;
  return new;
end $$;

create trigger degree_schedule_students_revision
after update of expected_graduation on students
for each row when (old.expected_graduation is distinct from new.expected_graduation)
execute function degree_schedule_bump_student_profile_revision();

create trigger degree_schedule_student_institutions_revision
after insert or delete or update of student_id, institution_id, relationship, catalog_year
on student_institutions for each row execute function degree_schedule_bump_student_revision();

create or replace function degree_schedule_bump_program_revision(p_program_id uuid)
returns void language plpgsql security definer
set search_path = pg_catalog, public
as $$
begin
  insert into public.degree_schedule_program_revisions(program_id, revision)
  values (p_program_id, 2)
  on conflict (program_id) do update
    set revision = degree_schedule_program_revisions.revision + 1,
        updated_at = clock_timestamp();
end $$;

create or replace function degree_schedule_requirement_revision()
returns trigger language plpgsql security definer
set search_path = pg_catalog, public
as $$
declare
  v_program_id uuid;
  v_old_program_id uuid;
begin
  if tg_table_name = 'requirement_groups' then
    v_program_id := case when tg_op = 'DELETE' then old.program_id else new.program_id end;
    v_old_program_id := case when tg_op = 'UPDATE' then old.program_id else null end;
  elsif tg_table_name = 'requirement_group_options' then
    select program_id into v_program_id from public.requirement_groups
    where id = case when tg_op = 'DELETE' then old.requirement_group_id else new.requirement_group_id end;
    if tg_op = 'UPDATE' then
      select program_id into v_old_program_id from public.requirement_groups where id = old.requirement_group_id;
    end if;
  else
    select g.program_id into v_program_id
    from public.requirement_group_options o join public.requirement_groups g on g.id = o.requirement_group_id
    where o.id = case when tg_op = 'DELETE' then old.requirement_group_option_id else new.requirement_group_option_id end;
    if tg_op = 'UPDATE' then
      select g.program_id into v_old_program_id
      from public.requirement_group_options o join public.requirement_groups g on g.id = o.requirement_group_id
      where o.id = old.requirement_group_option_id;
    end if;
  end if;
  if v_program_id is not null then perform public.degree_schedule_bump_program_revision(v_program_id); end if;
  if v_old_program_id is not null and v_old_program_id is distinct from v_program_id then
    perform public.degree_schedule_bump_program_revision(v_old_program_id);
  end if;
  return coalesce(new, old);
end $$;

create trigger degree_schedule_requirement_groups_revision
after insert or update or delete on requirement_groups
for each row execute function degree_schedule_requirement_revision();
create trigger degree_schedule_requirement_options_revision
after insert or update or delete on requirement_group_options
for each row execute function degree_schedule_requirement_revision();
create trigger degree_schedule_requirement_courses_revision
after insert or update or delete on requirement_group_option_courses
for each row execute function degree_schedule_requirement_revision();

create or replace function degree_schedule_program_definition_revision()
returns trigger language plpgsql security definer
set search_path = pg_catalog, public
as $$
begin
  perform public.degree_schedule_bump_program_revision(new.id);
  return new;
end $$;
create trigger degree_schedule_programs_revision
after update of institution_id, catalog_year on programs
for each row when (
  old.institution_id is distinct from new.institution_id
  or old.catalog_year is distinct from new.catalog_year
)
execute function degree_schedule_program_definition_revision();

create or replace function degree_schedule_bump_institution_revision(p_institution_id uuid)
returns void language plpgsql security definer
set search_path = pg_catalog, public
as $$
begin
  insert into public.degree_schedule_institution_revisions(institution_id, revision)
  values (p_institution_id, 2)
  on conflict (institution_id) do update
    set revision = degree_schedule_institution_revisions.revision + 1,
        updated_at = clock_timestamp();
end $$;

create or replace function degree_schedule_catalog_revision()
returns trigger language plpgsql security definer
set search_path = pg_catalog, public
as $$
declare
  v_institution_id uuid := case when tg_op = 'DELETE' then old.institution_id else new.institution_id end;
begin
  perform public.degree_schedule_bump_institution_revision(v_institution_id);
  if tg_op = 'UPDATE' and old.institution_id is distinct from new.institution_id then
    perform public.degree_schedule_bump_institution_revision(old.institution_id);
  end if;
  return coalesce(new, old);
end $$;

create trigger degree_schedule_course_catalog_revision
after insert or delete or update of institution_id, code, credit_min, coursedog_group_id
on course_catalog for each row execute function degree_schedule_catalog_revision();

create trigger degree_schedule_term_dates_revision
after insert or delete or update of institution_id, year, season, start_date, end_date
on academic_term_dates for each row execute function degree_schedule_catalog_revision();

create or replace function degree_schedule_institution_identity_revision()
returns trigger language plpgsql security definer
set search_path = pg_catalog, public
as $$
begin
  perform public.degree_schedule_bump_institution_revision(new.id);
  return new;
end $$;
create trigger degree_schedule_institutions_revision
after update of name on institutions
for each row when (old.name is distinct from new.name)
execute function degree_schedule_institution_identity_revision();

create or replace function get_degree_schedule_revisions(
  p_student_id uuid, p_program_id uuid
) returns jsonb
language plpgsql security definer
set search_path = pg_catalog, public
as $$
declare
  v_institution_id uuid;
  v_student_revision bigint;
  v_program_revision bigint;
  v_institution_revision bigint;
begin
  if not exists (select 1 from public.students where id = p_student_id) then
    raise exception using errcode = '23503', message = 'student does not exist';
  end if;
  select institution_id into v_institution_id from public.programs where id = p_program_id;
  if v_institution_id is null then
    raise exception using errcode = '23503', message = 'program does not exist';
  end if;
  insert into public.degree_schedule_student_revisions(student_id, program_id)
  values (p_student_id, p_program_id) on conflict do nothing;
  insert into public.degree_schedule_program_revisions(program_id)
  values (p_program_id) on conflict do nothing;
  insert into public.degree_schedule_institution_revisions(institution_id)
  values (v_institution_id) on conflict do nothing;
  select revision into v_student_revision from public.degree_schedule_student_revisions
  where student_id = p_student_id and program_id = p_program_id;
  select revision into v_program_revision from public.degree_schedule_program_revisions
  where program_id = p_program_id;
  select revision into v_institution_revision from public.degree_schedule_institution_revisions
  where institution_id = v_institution_id;
  return jsonb_build_object(
    'student_revision', v_student_revision,
    'program_revision', v_program_revision,
    'institution_revision', v_institution_revision
  );
end $$;

create or replace function replace_degree_requirement_selections(
  p_student_id uuid,
  p_program_id uuid,
  p_expected_student_revision bigint,
  p_expected_program_revision bigint,
  p_expected_institution_revision bigint,
  p_schedule_version text,
  p_selections jsonb
) returns jsonb
language plpgsql security definer
set search_path = pg_catalog, public
as $$
declare
  v_institution_id uuid;
  v_student_revision bigint;
  v_program_revision bigint;
  v_institution_revision bigint;
  v_current jsonb;
  v_desired jsonb;
  v_current_identity jsonb;
  v_desired_identity jsonb;
begin
  if p_schedule_version !~ '^sha256:[0-9a-f]{64}$' then
    raise exception using errcode = '23514', message = 'invalid schedule version';
  end if;
  if jsonb_typeof(p_selections) is distinct from 'array' then
    raise exception using errcode = '22023', message = 'selections must be a JSON array';
  end if;
  select institution_id into v_institution_id from public.programs where id = p_program_id;
  if v_institution_id is null or not exists (select 1 from public.students where id = p_student_id) then
    raise exception using errcode = '23503', message = 'student or program does not exist';
  end if;

  perform public.get_degree_schedule_revisions(p_student_id, p_program_id);
  select revision into v_student_revision from public.degree_schedule_student_revisions
    where student_id = p_student_id and program_id = p_program_id for update;
  select revision into v_program_revision from public.degree_schedule_program_revisions
    where program_id = p_program_id for update;
  select revision into v_institution_revision from public.degree_schedule_institution_revisions
    where institution_id = v_institution_id for update;

  if v_student_revision <> p_expected_student_revision
     or v_program_revision <> p_expected_program_revision
     or v_institution_revision <> p_expected_institution_revision then
    return jsonb_build_object(
      'status', 'REVISION_CONFLICT',
      'student_revision', v_student_revision,
      'program_revision', v_program_revision,
      'institution_revision', v_institution_revision
    );
  end if;

  if exists (
    select 1 from jsonb_to_recordset(p_selections)
      as x(requirement_group_id uuid, candidate_id text, course_codes text[])
    group by requirement_group_id having count(*) > 1
  ) then
    raise exception using errcode = '23505', message = 'duplicate requirement selection';
  end if;
  if exists (
    select 1 from jsonb_to_recordset(p_selections)
      as x(requirement_group_id uuid, candidate_id text, course_codes text[])
    where requirement_group_id is null or btrim(coalesce(candidate_id, '')) = ''
      or cardinality(course_codes) is null or cardinality(course_codes) = 0
      or array_position(course_codes, null) is not null
      or array_position(course_codes, '') is not null
  ) then
    raise exception using errcode = '23514', message = 'invalid requirement selection';
  end if;
  if exists (
    select 1 from jsonb_to_recordset(p_selections) as x(requirement_group_id uuid)
    left join public.requirement_groups g
      on g.id = x.requirement_group_id and g.program_id = p_program_id
    where g.id is null
  ) then
    raise exception using errcode = '23503', message = 'requirement does not belong to program';
  end if;

  select coalesce(jsonb_agg(jsonb_build_object(
    'requirement_group_id', requirement_group_id,
    'candidate_id', candidate_id,
    'course_codes', course_codes,
    'decision_version', decision_version
  ) order by requirement_group_id), '[]'::jsonb)
  into v_current
  from public.degree_requirement_selections
  where student_id = p_student_id and program_id = p_program_id;

  select coalesce(jsonb_agg(jsonb_build_object(
    'requirement_group_id', requirement_group_id,
    'candidate_id', candidate_id,
    'course_codes', course_codes
  ) order by requirement_group_id), '[]'::jsonb)
  into v_current_identity
  from public.degree_requirement_selections
  where student_id = p_student_id and program_id = p_program_id;

  select coalesce(jsonb_agg(jsonb_build_object(
    'requirement_group_id', requirement_group_id,
    'candidate_id', candidate_id,
    'course_codes', course_codes,
    'decision_version', p_schedule_version
  ) order by requirement_group_id), '[]'::jsonb)
  into v_desired
  from jsonb_to_recordset(p_selections)
    as x(requirement_group_id uuid, candidate_id text, course_codes text[]);

  select coalesce(jsonb_agg(jsonb_build_object(
    'requirement_group_id', requirement_group_id,
    'candidate_id', candidate_id,
    'course_codes', course_codes
  ) order by requirement_group_id), '[]'::jsonb)
  into v_desired_identity
  from jsonb_to_recordset(p_selections)
    as x(requirement_group_id uuid, candidate_id text, course_codes text[]);

  if v_current_identity = v_desired_identity then
    return jsonb_build_object(
      'status', 'UNCHANGED',
      'student_revision', v_student_revision,
      'program_revision', v_program_revision,
      'institution_revision', v_institution_revision,
      'selections', v_current
    );
  end if;

  perform set_config('app.degree_schedule_revision_bump_suppressed', 'on', true);
  delete from public.degree_requirement_selections s
  where s.student_id = p_student_id and s.program_id = p_program_id
    and not exists (
      select 1 from jsonb_to_recordset(p_selections) as x(requirement_group_id uuid)
      where x.requirement_group_id = s.requirement_group_id
    );
  insert into public.degree_requirement_selections(
    student_id, program_id, requirement_group_id, candidate_id, course_codes, decision_version
  )
  select p_student_id, p_program_id, requirement_group_id, candidate_id, course_codes, p_schedule_version
  from jsonb_to_recordset(p_selections)
    as x(requirement_group_id uuid, candidate_id text, course_codes text[])
  on conflict (student_id, program_id, requirement_group_id) do update
  set candidate_id = excluded.candidate_id,
      course_codes = excluded.course_codes,
      decision_version = excluded.decision_version,
      updated_at = clock_timestamp()
  where (degree_requirement_selections.candidate_id,
         degree_requirement_selections.course_codes,
         degree_requirement_selections.decision_version)
    is distinct from
        (excluded.candidate_id, excluded.course_codes, excluded.decision_version);
  perform set_config('app.degree_schedule_revision_bump_suppressed', 'off', true);

  update public.degree_schedule_student_revisions
  set revision = revision + 1, updated_at = clock_timestamp()
  where student_id = p_student_id and program_id = p_program_id
  returning revision into v_student_revision;

  select coalesce(jsonb_agg(jsonb_build_object(
    'requirement_group_id', requirement_group_id,
    'candidate_id', candidate_id,
    'course_codes', course_codes,
    'decision_version', decision_version
  ) order by requirement_group_id), '[]'::jsonb)
  into v_current from public.degree_requirement_selections
  where student_id = p_student_id and program_id = p_program_id;
  return jsonb_build_object(
    'status', 'APPLIED',
    'student_revision', v_student_revision,
    'program_revision', v_program_revision,
    'institution_revision', v_institution_revision,
    'selections', v_current
  );
end $$;

revoke all on function get_degree_schedule_revisions(uuid, uuid) from public, anon, authenticated;
revoke all on function replace_degree_requirement_selections(uuid, uuid, bigint, bigint, bigint, text, jsonb)
  from public, anon, authenticated;
grant execute on function get_degree_schedule_revisions(uuid, uuid) to service_role;
grant execute on function replace_degree_requirement_selections(uuid, uuid, bigint, bigint, bigint, text, jsonb)
  to service_role;

comment on function replace_degree_requirement_selections(uuid, uuid, bigint, bigint, bigint, text, jsonb)
is 'Service-role-only atomic complete-set replacement. Python must validate current candidates and schedule semantics before calling.';

revoke all on function degree_schedule_bump_student_revision() from public, anon, authenticated;
revoke all on function degree_schedule_bump_student_profile_revision() from public, anon, authenticated;
revoke all on function degree_schedule_bump_program_revision(uuid) from public, anon, authenticated;
revoke all on function degree_schedule_requirement_revision() from public, anon, authenticated;
revoke all on function degree_schedule_program_definition_revision() from public, anon, authenticated;
revoke all on function degree_schedule_bump_institution_revision(uuid) from public, anon, authenticated;
revoke all on function degree_schedule_catalog_revision() from public, anon, authenticated;
revoke all on function degree_schedule_institution_identity_revision() from public, anon, authenticated;
