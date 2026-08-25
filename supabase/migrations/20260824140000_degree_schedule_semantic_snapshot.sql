-- Service-only bridge from repository-local academic semantics into the
-- institution revision checked by Degree Schedule selection CAS.

create table degree_schedule_institution_semantics (
  institution_id uuid primary key references institutions(id) on delete cascade,
  local_catalog_fingerprint text not null
    check (local_catalog_fingerprint ~ '^sha256:[0-9a-f]{64}$'),
  planner_contract_version text not null
    check (btrim(planner_contract_version) <> ''),
  updated_at timestamptz not null default now()
);

alter table degree_schedule_institution_semantics enable row level security;
revoke all on degree_schedule_institution_semantics from anon, authenticated;
grant all on degree_schedule_institution_semantics to service_role;

create or replace function sync_degree_schedule_institution_semantics(
  p_institution_id uuid,
  p_local_catalog_fingerprint text,
  p_planner_contract_version text
) returns jsonb
language plpgsql security definer
set search_path = pg_catalog, public
as $$
declare
  v_current public.degree_schedule_institution_semantics%rowtype;
  v_revision bigint;
  v_status text;
begin
  if p_local_catalog_fingerprint !~ '^sha256:[0-9a-f]{64}$'
     or btrim(coalesce(p_planner_contract_version, '')) = '' then
    raise exception using errcode = '23514', message = 'invalid Degree Schedule semantics identity';
  end if;
  if not exists (select 1 from public.institutions where id = p_institution_id) then
    raise exception using errcode = '23503', message = 'institution does not exist';
  end if;

  insert into public.degree_schedule_institution_revisions(institution_id)
  values (p_institution_id) on conflict do nothing;
  select revision into v_revision
  from public.degree_schedule_institution_revisions
  where institution_id = p_institution_id
  for update;

  select * into v_current
  from public.degree_schedule_institution_semantics
  where institution_id = p_institution_id
  for update;

  if found
     and v_current.local_catalog_fingerprint = p_local_catalog_fingerprint
     and v_current.planner_contract_version = p_planner_contract_version then
    return jsonb_build_object(
      'status', 'UNCHANGED',
      'institution_revision', v_revision,
      'local_catalog_fingerprint', v_current.local_catalog_fingerprint,
      'planner_contract_version', v_current.planner_contract_version
    );
  end if;

  if v_current.institution_id is null then
    insert into public.degree_schedule_institution_semantics(
      institution_id, local_catalog_fingerprint, planner_contract_version
    ) values (
      p_institution_id, p_local_catalog_fingerprint, p_planner_contract_version
    );
    v_status := 'REGISTERED';
  else
    update public.degree_schedule_institution_semantics
    set local_catalog_fingerprint = p_local_catalog_fingerprint,
        planner_contract_version = p_planner_contract_version,
        updated_at = clock_timestamp()
    where institution_id = p_institution_id;
    v_status := 'UPDATED';
  end if;

  update public.degree_schedule_institution_revisions
  set revision = revision + 1, updated_at = clock_timestamp()
  where institution_id = p_institution_id
  returning revision into v_revision;

  return jsonb_build_object(
    'status', v_status,
    'institution_revision', v_revision,
    'local_catalog_fingerprint', p_local_catalog_fingerprint,
    'planner_contract_version', p_planner_contract_version
  );
end $$;

revoke all on function sync_degree_schedule_institution_semantics(uuid, text, text)
  from public, anon, authenticated;
grant execute on function sync_degree_schedule_institution_semantics(uuid, text, text)
  to service_role;

comment on function sync_degree_schedule_institution_semantics(uuid, text, text)
is 'Service-only idempotent registration of local catalog and planner semantics. A changed identity advances the institution revision used by selection CAS.';
