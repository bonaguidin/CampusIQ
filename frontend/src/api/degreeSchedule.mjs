export function isSkippedDegreeSchedule(result) {
  return 'status' in result && result.status === 'skipped';
}

// identity.slug present -> the local, non-Postgres demo counterpart (no
// token sent); otherwise the session-scoped /me route, same identity-branch
// shape analysisApi.mjs's analysisPath() already uses.
function degreeSchedulePath(identity) {
  if (identity.slug) return [`/api/students/${encodeURIComponent(identity.slug)}/schedule`, undefined];
  if (!identity.accessToken) throw new Error('Degree schedule requires a session.');
  return ['/api/v2/student/me/schedule', identity.accessToken];
}

export async function fetchDegreeSchedule(identity) {
  const [url, token] = degreeSchedulePath(identity);
  const headers = { Accept: 'application/json' };
  if (token) headers.Authorization = `Bearer ${token}`;
  let response;
  try {
    response = await fetch(url, { method: 'GET', headers });
  } catch {
    throw new Error('Degree schedule is unavailable.');
  }

  let body = null;
  try { body = await response.json(); } catch { /* handled by the status check */ }
  if (response.status === 200 && body && typeof body === 'object') {
    return body;
  }
  const detail =
    body && typeof body === 'object' && 'detail' in body
      ? String(body.detail)
      : 'Degree schedule is unavailable.';
  throw new Error(detail);
}
