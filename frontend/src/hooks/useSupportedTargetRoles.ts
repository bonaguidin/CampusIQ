import { useEffect, useState } from 'react';
import { useAuth } from '../auth/useAuth';
import { getCareerRoleOptions } from '../api/profile';

/**
 * The curated target-role vocabulary GET /career-role-options exposes,
 * fetched once per mount and shared by every place that needs to know
 * whether a role is analysis-supported -- the target-role editor (to offer
 * only addable supported roles) and Course Discovery's role selector (to
 * mark unsupported roles instead of letting a student pick one and run into
 * a silent empty result). A plain boolean-shaped `null` while loading keeps
 * every caller's "don't know yet" state from being confused with "zero
 * supported roles", which would otherwise look identical.
 */
export function useSupportedTargetRoles(): string[] | null {
  const { session } = useAuth();
  const [roles, setRoles] = useState<string[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    const accessToken = session?.access_token;
    if (!accessToken) return;
    getCareerRoleOptions(accessToken)
      .then((result) => { if (!cancelled) setRoles(result); })
      .catch(() => { if (!cancelled) setRoles(null); });
    return () => { cancelled = true; };
  }, [session?.access_token]);

  return roles;
}
