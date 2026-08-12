-- Staging and atomic application for repeat resume uploads.
--
-- Canonical students/career tables remain authoritative. A new resume is held
-- here until the owning student resolves its proposed changes; no existing
-- canonical row is backfilled or rewritten by this migration.

create table resume_reconciliations (
  id uuid primary key default gen_random_uuid(),
  student_id uuid not null references students (id) on delete cascade,
  status text not null default 'pending'
    check (status in ('pending', 'applied', 'discarded')),
  academic_proposal jsonb not null default '{}'::jsonb
    check (jsonb_typeof(academic_proposal) = 'object'),
  skills_proposal jsonb not null default '{}'::jsonb
    check (jsonb_typeof(skills_proposal) = 'object'),
  base_student_updated_at timestamptz null,
  base_career_profile_updated_at timestamptz null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  applied_at timestamptz null,
  unique (id, student_id),
  check ((status = 'applied') = (applied_at is not null))
);

create table resume_reconciliation_items (
  id uuid primary key default gen_random_uuid(),
  reconciliation_id uuid not null,
  student_id uuid not null,
  domain text not null
    check (domain in ('work_experience', 'project', 'certification')),
  classification text not null
    check (classification in ('add', 'update', 'unchanged', 'possible_match')),
  canonical_row_id uuid null,
  canonical_row_updated_at timestamptz null,
  proposed_value jsonb not null
    check (jsonb_typeof(proposed_value) = 'object'),
  decision text null
    check (decision is null or decision in ('accept', 'keep', 'ignore')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  foreign key (reconciliation_id, student_id)
    references resume_reconciliations (id, student_id) on delete cascade,
  check (
    (classification = 'add' and canonical_row_id is null and canonical_row_updated_at is null)
    or
    (classification in ('update', 'possible_match') and canonical_row_id is not null)
    or
    (classification = 'unchanged')
  )
);

-- A student may retain applied/discarded history, but only one active review.
create unique index resume_reconciliations_one_pending_per_student
  on resume_reconciliations (student_id)
  where status = 'pending';

create index resume_reconciliation_items_reconciliation_idx
  on resume_reconciliation_items (reconciliation_id);

alter table resume_reconciliations enable row level security;
alter table resume_reconciliation_items enable row level security;

grant select, insert, update, delete on resume_reconciliations to authenticated;
grant select, insert, update, delete on resume_reconciliation_items to authenticated;

create policy resume_reconciliations_owner_all
  on resume_reconciliations for all
  to authenticated
  using (
    exists (
      select 1 from students
      where students.id = resume_reconciliations.student_id
        and students.auth_user_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1 from students
      where students.id = resume_reconciliations.student_id
        and students.auth_user_id = auth.uid()
    )
  );

create policy resume_reconciliation_items_owner_all
  on resume_reconciliation_items for all
  to authenticated
  using (
    exists (
      select 1 from students
      where students.id = resume_reconciliation_items.student_id
        and students.auth_user_id = auth.uid()
    )
  )
  with check (
    exists (
      select 1 from students
      where students.id = resume_reconciliation_items.student_id
        and students.auth_user_id = auth.uid()
    )
  );

-- Applies one fully reviewed proposal in a single PostgreSQL transaction.
-- SECURITY DEFINER is required because canonical RLS policies use auth.uid()
-- while this function must lock and validate all involved rows consistently.
-- Ownership is derived from auth.uid(), never from a client student_id.
create or replace function apply_resume_reconciliation(p_reconciliation_id uuid)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_auth_user_id uuid := auth.uid();
  v_student students%rowtype;
  v_reconciliation resume_reconciliations%rowtype;
  v_career career_profiles%rowtype;
  v_item resume_reconciliation_items%rowtype;
  v_now timestamptz := now();
  v_entry jsonb;
  v_value text;
  v_updated int := 0;
  v_inserted int := 0;
begin
  if v_auth_user_id is null then
    raise exception 'RECONCILIATION_UNAUTHENTICATED' using errcode = 'P0001';
  end if;

  select r.* into v_reconciliation
  from resume_reconciliations r
  join students s on s.id = r.student_id
  where r.id = p_reconciliation_id
    and s.auth_user_id = v_auth_user_id
  for update of r;

  if not found then
    raise exception 'RECONCILIATION_NOT_FOUND' using errcode = 'P0001';
  end if;
  if v_reconciliation.status <> 'pending' then
    raise exception 'RECONCILIATION_NOT_PENDING' using errcode = 'P0001';
  end if;

  select * into v_student
  from students
  where id = v_reconciliation.student_id
  for update;

  if v_student.updated_at is distinct from v_reconciliation.base_student_updated_at then
    raise exception 'RECONCILIATION_STALE' using errcode = 'P0001';
  end if;

  select * into v_career
  from career_profiles
  where student_id = v_reconciliation.student_id
  for update;

  if found then
    if v_career.updated_at is distinct from v_reconciliation.base_career_profile_updated_at then
      raise exception 'RECONCILIATION_STALE' using errcode = 'P0001';
    end if;
  elsif v_reconciliation.base_career_profile_updated_at is not null then
    raise exception 'RECONCILIATION_STALE' using errcode = 'P0001';
  end if;

  -- Validate every canonical reference and stale marker before any write.
  for v_item in
    select * from resume_reconciliation_items
    where reconciliation_id = v_reconciliation.id
    order by created_at, id
    for update
  loop
    if v_item.student_id <> v_reconciliation.student_id then
      raise exception 'RECONCILIATION_OWNERSHIP_MISMATCH' using errcode = 'P0001';
    end if;
    if v_item.classification = 'possible_match' and v_item.decision is null then
      raise exception 'RECONCILIATION_UNRESOLVED_MATCH' using errcode = 'P0001';
    end if;

    if v_item.canonical_row_id is not null then
      if v_item.domain = 'work_experience' then
        perform 1 from work_experience
        where id = v_item.canonical_row_id
          and student_id = v_reconciliation.student_id
          and (
            v_item.classification not in ('update', 'possible_match')
            or updated_at is not distinct from v_item.canonical_row_updated_at
          )
        for update;
      elsif v_item.domain = 'project' then
        perform 1 from projects
        where id = v_item.canonical_row_id
          and student_id = v_reconciliation.student_id
          and (
            v_item.classification not in ('update', 'possible_match')
            or updated_at is not distinct from v_item.canonical_row_updated_at
          )
        for update;
      elsif v_item.domain = 'certification' then
        perform 1 from certifications
        where id = v_item.canonical_row_id
          and student_id = v_reconciliation.student_id
          and (
            v_item.classification not in ('update', 'possible_match')
            or updated_at is not distinct from v_item.canonical_row_updated_at
          )
        for update;
      end if;
      if not found then
        raise exception 'RECONCILIATION_STALE' using errcode = 'P0001';
      end if;
    end if;
  end loop;

  -- Academic facts are accepted individually and omission never clears data.
  v_entry := v_reconciliation.academic_proposal -> 'major_current';
  if v_entry ->> 'decision' = 'accept'
     and nullif(btrim(v_entry ->> 'value'), '') is not null then
    update students
    set major_current = btrim(v_entry ->> 'value'), updated_at = v_now
    where id = v_reconciliation.student_id;
    v_student.updated_at := v_now;
  end if;

  v_entry := v_reconciliation.academic_proposal -> 'expected_graduation';
  if v_entry ->> 'decision' = 'accept'
     and nullif(btrim(v_entry ->> 'value'), '') is not null then
    update students
    set expected_graduation = btrim(v_entry ->> 'value'), updated_at = v_now
    where id = v_reconciliation.student_id;
    v_student.updated_at := v_now;
  end if;

  -- Skills merge additively. Existing spelling/casing wins on duplicates.
  if v_career.id is not null then
    for v_entry in
      select value from jsonb_array_elements(
        coalesce(v_reconciliation.skills_proposal -> 'technical', '[]'::jsonb)
      )
    loop
      if v_entry ->> 'decision' = 'accept' then
        v_value := nullif(btrim(v_entry ->> 'value'), '');
        if v_value is not null and not exists (
          select 1 from unnest(coalesce(v_career.skills_technical, '{}'::text[])) skill
          where lower(btrim(skill)) = lower(v_value)
        ) then
          v_career.skills_technical := array_append(
            coalesce(v_career.skills_technical, '{}'::text[]), v_value
          );
        end if;
      end if;
    end loop;

    for v_entry in
      select value from jsonb_array_elements(
        coalesce(v_reconciliation.skills_proposal -> 'soft', '[]'::jsonb)
      )
    loop
      if v_entry ->> 'decision' = 'accept' then
        v_value := nullif(btrim(v_entry ->> 'value'), '');
        if v_value is not null and not exists (
          select 1 from unnest(coalesce(v_career.skills_soft, '{}'::text[])) skill
          where lower(btrim(skill)) = lower(v_value)
        ) then
          v_career.skills_soft := array_append(
            coalesce(v_career.skills_soft, '{}'::text[]), v_value
          );
        end if;
      end if;
    end loop;

    if v_career.skills_technical is distinct from (
         select skills_technical from career_profiles where id = v_career.id
       ) or v_career.skills_soft is distinct from (
         select skills_soft from career_profiles where id = v_career.id
       ) then
      update career_profiles
      set skills_technical = v_career.skills_technical,
          skills_soft = v_career.skills_soft,
          confirmed_at = v_now,
          updated_at = v_now
      where id = v_career.id;
    end if;
  end if;

  for v_item in
    select * from resume_reconciliation_items
    where reconciliation_id = v_reconciliation.id
      and decision = 'accept'
      and classification in ('add', 'update', 'possible_match')
    order by created_at, id
  loop
    if v_item.domain = 'work_experience' then
      if v_item.classification = 'add' then
        if v_career.id is null then
          raise exception 'RECONCILIATION_CAREER_PROFILE_REQUIRED' using errcode = 'P0001';
        end if;
        insert into work_experience (
          career_profile_id, student_id, employer, role, duration, location,
          description, skills_gained, source, confirmed_at, updated_at
        ) values (
          v_career.id, v_reconciliation.student_id,
          nullif(btrim(v_item.proposed_value ->> 'employer'), ''),
          nullif(btrim(v_item.proposed_value ->> 'role'), ''),
          nullif(btrim(v_item.proposed_value ->> 'duration'), ''),
          nullif(btrim(v_item.proposed_value ->> 'location'), ''),
          nullif(btrim(v_item.proposed_value ->> 'description'), ''),
          case when jsonb_typeof(v_item.proposed_value -> 'skills_gained') = 'array'
            then array(select jsonb_array_elements_text(v_item.proposed_value -> 'skills_gained'))
            else '{}'::text[] end,
          'resume_parse', v_now, v_now
        );
        v_inserted := v_inserted + 1;
      else
        update work_experience set
          employer = case when v_item.proposed_value ? 'employer'
            then nullif(btrim(v_item.proposed_value ->> 'employer'), '') else employer end,
          role = case when v_item.proposed_value ? 'role'
            then nullif(btrim(v_item.proposed_value ->> 'role'), '') else role end,
          duration = case when v_item.proposed_value ? 'duration'
            then nullif(btrim(v_item.proposed_value ->> 'duration'), '') else duration end,
          location = case when v_item.proposed_value ? 'location'
            then nullif(btrim(v_item.proposed_value ->> 'location'), '') else location end,
          description = case when v_item.proposed_value ? 'description'
            then nullif(btrim(v_item.proposed_value ->> 'description'), '') else description end,
          skills_gained = case
            when jsonb_typeof(v_item.proposed_value -> 'skills_gained') = 'array'
              then array(select jsonb_array_elements_text(v_item.proposed_value -> 'skills_gained'))
            else skills_gained end,
          confirmed_at = v_now, updated_at = v_now
        where id = v_item.canonical_row_id
          and student_id = v_reconciliation.student_id;
        v_updated := v_updated + 1;
      end if;

    elsif v_item.domain = 'project' then
      if v_item.classification = 'add' then
        if v_career.id is null then
          raise exception 'RECONCILIATION_CAREER_PROFILE_REQUIRED' using errcode = 'P0001';
        end if;
        insert into projects (
          career_profile_id, student_id, name, timeframe, description, tools,
          source, confirmed_at, updated_at
        ) values (
          v_career.id, v_reconciliation.student_id,
          nullif(btrim(v_item.proposed_value ->> 'name'), ''),
          nullif(btrim(v_item.proposed_value ->> 'timeframe'), ''),
          nullif(btrim(v_item.proposed_value ->> 'description'), ''),
          case when jsonb_typeof(v_item.proposed_value -> 'tools') = 'array'
            then array(select jsonb_array_elements_text(v_item.proposed_value -> 'tools'))
            else '{}'::text[] end,
          'resume_parse', v_now, v_now
        );
        v_inserted := v_inserted + 1;
      else
        update projects set
          name = case when v_item.proposed_value ? 'name'
            then nullif(btrim(v_item.proposed_value ->> 'name'), '') else name end,
          timeframe = case when v_item.proposed_value ? 'timeframe'
            then nullif(btrim(v_item.proposed_value ->> 'timeframe'), '') else timeframe end,
          description = case when v_item.proposed_value ? 'description'
            then nullif(btrim(v_item.proposed_value ->> 'description'), '') else description end,
          tools = case when jsonb_typeof(v_item.proposed_value -> 'tools') = 'array'
            then array(select jsonb_array_elements_text(v_item.proposed_value -> 'tools'))
            else tools end,
          confirmed_at = v_now, updated_at = v_now
        where id = v_item.canonical_row_id
          and student_id = v_reconciliation.student_id;
        v_updated := v_updated + 1;
      end if;

    elsif v_item.domain = 'certification' then
      if v_item.classification = 'add' then
        if v_career.id is null then
          raise exception 'RECONCILIATION_CAREER_PROFILE_REQUIRED' using errcode = 'P0001';
        end if;
        insert into certifications (
          career_profile_id, student_id, name, issuer, status, date,
          source, confirmed_at, updated_at
        ) values (
          v_career.id, v_reconciliation.student_id,
          nullif(btrim(v_item.proposed_value ->> 'name'), ''),
          nullif(btrim(v_item.proposed_value ->> 'issuer'), ''),
          nullif(btrim(v_item.proposed_value ->> 'status'), ''),
          nullif(btrim(v_item.proposed_value ->> 'date'), ''),
          'resume_parse', v_now, v_now
        );
        v_inserted := v_inserted + 1;
      else
        update certifications set
          name = case when v_item.proposed_value ? 'name'
            then nullif(btrim(v_item.proposed_value ->> 'name'), '') else name end,
          issuer = case when v_item.proposed_value ? 'issuer'
            then nullif(btrim(v_item.proposed_value ->> 'issuer'), '') else issuer end,
          status = case when v_item.proposed_value ? 'status'
            then nullif(btrim(v_item.proposed_value ->> 'status'), '') else status end,
          date = case when v_item.proposed_value ? 'date'
            then nullif(btrim(v_item.proposed_value ->> 'date'), '') else date end,
          confirmed_at = v_now, updated_at = v_now
        where id = v_item.canonical_row_id
          and student_id = v_reconciliation.student_id;
        v_updated := v_updated + 1;
      end if;
    end if;
  end loop;

  update resume_reconciliations
  set status = 'applied', applied_at = v_now, updated_at = v_now
  where id = v_reconciliation.id;

  return jsonb_build_object(
    'status', 'applied',
    'reconciliation_id', v_reconciliation.id,
    'inserted', v_inserted,
    'updated', v_updated
  );
end;
$$;

revoke all on function apply_resume_reconciliation(uuid) from public;
grant execute on function apply_resume_reconciliation(uuid) to authenticated;

comment on function apply_resume_reconciliation(uuid) is
  'Atomically applies one authenticated student-owned pending resume reconciliation. '
  'Raises RECONCILIATION_STALE when its canonical comparison base changed.';
