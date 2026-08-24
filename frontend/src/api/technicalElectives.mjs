export function isSkippedTechnicalElectives(result) {
  return 'status' in result && result.status === 'skipped';
}

// identity.slug present -> the local, non-Postgres demo counterpart (no
// token sent); otherwise the session-scoped /me route, same identity-branch
// shape analysisApi.mjs's analysisPath() already uses.
function technicalElectivesPath(identity) {
  if (identity.slug) {
    return [`/api/students/${encodeURIComponent(identity.slug)}/degree-plan/technical-electives`, undefined];
  }
  if (!identity.accessToken) throw new Error('Technical elective options require a session.');
  return ['/api/v2/student/me/degree-plan/technical-electives', identity.accessToken];
}

export async function fetchTechnicalElectiveCandidates(identity) {
  const [url, token] = technicalElectivesPath(identity);
  const headers = { Accept: 'application/json' };
  if (token) headers.Authorization = `Bearer ${token}`;
  let response;
  try {
    response = await fetch(url, { method: 'GET', headers });
  } catch {
    throw new Error('Technical elective options are unavailable.');
  }
  let body = null;
  try { body = await response.json(); } catch { /* handled below */ }
  if (response.status === 200 && body && typeof body === 'object') {
    return body;
  }
  const detail = body && typeof body === 'object' && 'detail' in body
    ? String(body.detail)
    : 'Technical elective options are unavailable.';
  throw new Error(detail);
}
