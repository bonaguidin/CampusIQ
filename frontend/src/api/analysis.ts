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

async function postAnalysis<T>(path: string, accessToken?: string): Promise<FeatureResult<T>> {
  const response = await fetch(path, {
    method: 'POST',
    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : undefined,
  });
  if (!response.ok) {
    throw await analysisFailure(response);
  }
  return (await response.json()) as FeatureResult<T>;
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
