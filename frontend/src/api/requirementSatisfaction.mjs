export function isSkippedRequirementSatisfaction(result) {
  return 'status' in result && result.status === 'skipped';
}

// identity.slug present -> the local, non-Postgres demo counterpart (no
// token sent); otherwise the session-scoped /me route, same identity-branch
// shape analysisApi.mjs's analysisPath() already uses.
function requirementSatisfactionPath(identity) {
  if (identity.slug) {
    return [`/api/students/${encodeURIComponent(identity.slug)}/requirement-satisfaction`, undefined];
  }
  if (!identity.accessToken) throw new Error('Requirement satisfaction requires a session.');
  return ['/api/v2/student/me/requirement-satisfaction', identity.accessToken];
}

// Same send()/auth() shape as api/planning.ts: a plain authenticated read,
// with no AI work and no cold start to budget for.
async function send(url, init) {
  try {
    const response = await fetch(url, init);
    let body = null;
    try { body = await response.json(); } catch { /* handled by the status check below */ }
    return { status: response.status, body };
  } catch {
    return { status: 0, body: null };
  }
}

export async function fetchRequirementSatisfaction(identity) {
  const [url, token] = requirementSatisfactionPath(identity);
  const headers = { Accept: 'application/json' };
  if (token) headers.Authorization = `Bearer ${token}`;
  const { status, body } = await send(url, { method: 'GET', headers });
  if (status === 200 && body && typeof body === 'object') {
    return body;
  }
  const detail =
    body && typeof body === 'object' && 'detail' in body
      ? String(body.detail)
      : 'Requirement satisfaction is unavailable.';
  throw new Error(detail);
}
