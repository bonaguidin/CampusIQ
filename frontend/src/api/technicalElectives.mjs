export function isSkippedTechnicalElectives(result) {
  return 'status' in result && result.status === 'skipped';
}

export async function fetchTechnicalElectiveCandidates(token) {
  let response;
  try {
    response = await fetch('/api/v2/student/me/degree-plan/technical-electives', {
      method: 'GET',
      headers: { Accept: 'application/json', Authorization: `Bearer ${token}` },
    });
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
