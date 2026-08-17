import type { MeProfile } from '../types/studentIntelligenceProfile';

export interface ProfileChanges {
  classification?: string;
  major_current?: string;
  major_intended?: string;
  expected_graduation?: string | null;
  ai_anxiety_level?: 'low' | 'moderate' | 'high' | 'not_sure' | null;
  target_roles?: string[];
  interests?: string[];
  skills_technical?: string[];
  skills_soft?: string[];
}

export async function updateProfile(
  accessToken: string,
  changes: ProfileChanges,
): Promise<MeProfile> {
  const response = await fetch('/api/v2/student/me/profile', {
    method: 'PATCH',
    headers: {
      Accept: 'application/json',
      Authorization: `Bearer ${accessToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(changes),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? 'Your profile could not be saved.');
  }
  return response.json() as Promise<MeProfile>;
}

/**
 * The curated target-role vocabulary career analysis (FIT/GAP/SHIFT/Course
 * Discovery) has coverage for. Static and the same for every student, but
 * kept behind the authenticated /me surface like every other route here
 * rather than made public.
 */
export async function getCareerRoleOptions(accessToken: string): Promise<string[]> {
  const response = await fetch('/api/v2/student/me/career-role-options', {
    headers: {
      Accept: 'application/json',
      Authorization: `Bearer ${accessToken}`,
    },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? 'Supported target roles could not be loaded.');
  }
  const body = (await response.json()) as { roles: string[] };
  return body.roles;
}
