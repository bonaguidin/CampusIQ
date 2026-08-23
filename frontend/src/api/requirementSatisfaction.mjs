export function isSkippedRequirementSatisfaction(result) {
  return 'status' in result && result.status === 'skipped';
}

const REQUIREMENT_SATISFACTION_URL = '/api/v2/student/me/requirement-satisfaction';

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

export async function fetchRequirementSatisfaction(token) {
  const { status, body } = await send(REQUIREMENT_SATISFACTION_URL, {
    method: 'GET',
    headers: { Accept: 'application/json', Authorization: `Bearer ${token}` },
  });
  if (status === 200 && body && typeof body === 'object') {
    return body;
  }
  const detail =
    body && typeof body === 'object' && 'detail' in body
      ? String(body.detail)
      : 'Requirement satisfaction is unavailable.';
  throw new Error(detail);
}
