import type { MeProfile } from '../types/studentIntelligenceProfile';

export interface ProfileChanges {
  classification?: string;
  major_current?: string;
  major_intended?: string;
  expected_graduation?: string;
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
