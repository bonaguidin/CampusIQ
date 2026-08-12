-- Supabase's function default privileges grant EXECUTE directly to anon in
-- addition to PUBLIC. The staging migration revoked PUBLIC; revoke the direct
-- anonymous grant as well while preserving authenticated application access.

revoke execute on function public.apply_resume_reconciliation(uuid) from anon;

-- Fail this migration transaction if the resulting grant posture differs
-- from the intended authenticated-only boundary.
do $$
declare
  v_function oid := 'public.apply_resume_reconciliation(uuid)'::regprocedure::oid;
begin
  if has_function_privilege('anon', v_function, 'EXECUTE') then
    raise exception 'anon retains EXECUTE on apply_resume_reconciliation(uuid)';
  end if;

  if not has_function_privilege('authenticated', v_function, 'EXECUTE') then
    raise exception 'authenticated lacks EXECUTE on apply_resume_reconciliation(uuid)';
  end if;

  if exists (
    select 1
    from pg_proc p
    cross join lateral aclexplode(
      coalesce(p.proacl, acldefault('f', p.proowner))
    ) privilege
    where p.oid = v_function
      and privilege.grantee = 0
      and privilege.privilege_type = 'EXECUTE'
  ) then
    raise exception 'PUBLIC retains EXECUTE on apply_resume_reconciliation(uuid)';
  end if;
end;
$$;
