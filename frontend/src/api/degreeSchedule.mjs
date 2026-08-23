export function isSkippedDegreeSchedule(result) {
  return 'status' in result && result.status === 'skipped';
}

const DEGREE_SCHEDULE_URL = '/api/v2/student/me/schedule';

export async function fetchDegreeSchedule(token) {
  let response;
  try {
    response = await fetch(DEGREE_SCHEDULE_URL, {
      method: 'GET',
      headers: { Accept: 'application/json', Authorization: `Bearer ${token}` },
    });
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
