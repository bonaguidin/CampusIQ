import { detailToText } from '../lib/resumeApi.mjs';

async function analysisFailure(response) {
  const body = await response.json().catch(() => null);
  const detail = body?.detail;
  if (response.status === 429) {
    return new Error(
      typeof detail === 'string' && detail.toLowerCase().includes('busy')
        ? 'The analysis service is busy right now. Try again in a moment.'
        : 'Too many requests. Wait a minute and try again.',
    );
  }
  const fallback = `Analysis request failed (${response.status}).`;
  return new Error(detailToText(detail, fallback));
}

async function postAnalysis(path, accessToken, body) {
  const headers = {};
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch(path, {
    method: 'POST',
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) throw await analysisFailure(response);
  return response.json();
}

export async function getCachedAnalysis(feature, accessToken) {
  const response = await fetch(`/api/v2/student/me/analysis-cache/${feature}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (response.status === 404) return null;
  if (!response.ok) throw await analysisFailure(response);
  return response.json();
}

function analysisPath(identity, feature) {
  if (identity.slug) {
    return [`/api/students/${encodeURIComponent(identity.slug)}/analyze/${feature}`];
  }
  if (!identity.accessToken) throw new Error('Authenticated analysis requires a session.');
  return [`/api/v2/student/me/analyze/${feature}`, identity.accessToken];
}

export function analyzeGap(identity) {
  return postAnalysis(...analysisPath(identity, 'gap'));
}

export function analyzeFit(identity) {
  return postAnalysis(...analysisPath(identity, 'fit'));
}

export function analyzeShift(identity) {
  return postAnalysis(...analysisPath(identity, 'shift'));
}

export function analyzeProfessorComments(identity) {
  return postAnalysis(...analysisPath(identity, 'professor-comments'));
}

export function analyzeCourseDiscovery(identity, targetRole) {
  const [path, token] = analysisPath(identity, 'course-discovery');
  return postAnalysis(path, token, targetRole ? { target_role: targetRole } : undefined);
}

export function analyzeActionPlan(identity, targetRole) {
  const body = targetRole ? { target_role: targetRole } : undefined;
  if (identity.slug) {
    // Demo counterpart to the real /me/action-plan route below. Named
    // .../analyze/action-plan (not .../action-plan) so it rides the same
    // slug-addressed /analyze/:feature route analysisPath() already builds.
    return postAnalysis(
      `/api/students/${encodeURIComponent(identity.slug)}/analyze/action-plan`,
      undefined,
      body,
    );
  }
  if (!identity.accessToken) throw new Error('Authenticated analysis requires a session.');
  return postAnalysis('/api/v2/student/me/action-plan', identity.accessToken, body);
}
