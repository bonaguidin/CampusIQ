// Bridge to GradusIQ_career/api.py — the FastAPI wrapper around orchestrator.run_feature().
// Demo identity is a slug. Authenticated identity is exclusively the bearer
// token sent to /me; no student id or slug is accepted for the real path.

import { detailToText } from '../lib/resumeApi.mjs';
import type {
  FeatureResult,
  FitAnalysisData,
  GapAnalysisData,
  ShiftAnalysisData,
  ProfessorCommentAnalysisData,
  CourseDiscoveryData,
  ActionPlanPreviewResponse,
} from '../types/analysis';

export interface AnalysisIdentity {
  slug: string | null;
  accessToken: string | null;
}

/**
 * Turn a failed analysis response into a sentence that names the cause.
 *
 * This used to be `Analysis request failed (${status}).` with the body
 * discarded, which made every failure mode indistinguishable at the point it
 * mattered most: two unrelated 429s (the shared request rate limit and the AI
 * concurrency gate) differ only by their `detail`, and the remedy differs too
 * -- wait a minute vs retry now. Diagnosing one of those cost a session of
 * log-reading that reading this body would have answered immediately.
 *
 * The 429 split mirrors resumeApi.mjs's `readFailure`, which already draws
 * exactly this distinction; the resume and transcript paths were given it and
 * the analysis path was not.
 */
async function analysisFailure(response: Response): Promise<Error> {
  const body = await response.json().catch(() => null) as { detail?: unknown } | null;
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

// TResult is the whole resolved JSON body, not a payload nested inside it.
// Every existing caller passes FeatureResult<X> as TResult, inferred from
// each wrapper's own return-type annotation below, so nothing about those
// call sites changes. This lets analyzeActionPlan reuse the same request/
// error-handling logic even though its response is not a FeatureResult
// (it has action_plan/dependency_order in place of data/errors/missing_fields).
async function postAnalysis<TResult>(
  path: string,
  accessToken?: string,
  body?: unknown,
): Promise<TResult> {
  const headers: Record<string, string> = {};
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch(path, {
    method: 'POST',
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    throw await analysisFailure(response);
  }
  return (await response.json()) as TResult;
}

function analysisPath(identity: AnalysisIdentity, feature: string): [string, string?] {
  if (identity.slug) {
    return [`/api/students/${encodeURIComponent(identity.slug)}/analyze/${feature}`];
  }
  if (!identity.accessToken) throw new Error('Authenticated analysis requires a session.');
  return [`/api/v2/student/me/analyze/${feature}`, identity.accessToken];
}

export function analyzeGap(identity: AnalysisIdentity): Promise<FeatureResult<GapAnalysisData>> {
  return postAnalysis(...analysisPath(identity, 'gap'));
}

export function analyzeFit(identity: AnalysisIdentity): Promise<FeatureResult<FitAnalysisData>> {
  return postAnalysis(...analysisPath(identity, 'fit'));
}

export function analyzeShift(identity: AnalysisIdentity): Promise<FeatureResult<ShiftAnalysisData>> {
  return postAnalysis(...analysisPath(identity, 'shift'));
}

export function analyzeProfessorComments(identity: AnalysisIdentity): Promise<FeatureResult<ProfessorCommentAnalysisData>> {
  return postAnalysis(...analysisPath(identity, 'professor-comments'));
}

/**
 * targetRole is the only thing this ever sends. The backend derives
 * everything else (student identity, canonical profile, CareerSkillNeed[])
 * itself from the trusted session — sending anything more would be rejected
 * anyway (CourseDiscoveryRequest is extra="forbid"), but the point is this
 * function structurally cannot construct that payload in the first place.
 * Omit targetRole (or pass null/undefined) to let the backend auto-select
 * the student's sole confirmed target role, exactly as CourseDiscoveryRequest
 * already allows.
 */
export function analyzeCourseDiscovery(
  identity: AnalysisIdentity,
  targetRole?: string | null,
): Promise<FeatureResult<CourseDiscoveryData>> {
  const [path, token] = analysisPath(identity, 'course-discovery');
  return postAnalysis(path, token, targetRole ? { target_role: targetRole } : undefined);
}

/**
 * Read-only dependency-order preview over the student's own, freshly
 * computed Course Discovery result -- not a schedule, not persisted. Bespoke
 * URL: this endpoint lives at /api/v2/student/me/action-plan, not under
 * /analyze/, and has no demo-slug equivalent (authenticated only), so it
 * cannot reuse analysisPath(). Sends only target_role, same as
 * analyzeCourseDiscovery -- the backend recomputes trusted Course Discovery
 * server-side and derives everything else from the session.
 */
export function analyzeActionPlan(
  identity: AnalysisIdentity,
  targetRole?: string | null,
): Promise<ActionPlanPreviewResponse> {
  if (!identity.accessToken) throw new Error('Authenticated analysis requires a session.');
  return postAnalysis(
    '/api/v2/student/me/action-plan',
    identity.accessToken,
    targetRole ? { target_role: targetRole } : undefined,
  );
}
