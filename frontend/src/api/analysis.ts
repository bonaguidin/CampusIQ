// Bridge to GradusIQ_career/api.py — the FastAPI wrapper around orchestrator.run_feature().
// Demo identity is a slug. Authenticated identity is exclusively the bearer
// token sent to /me; no student id or slug is accepted for the real path.

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

async function postAnalysis<T>(path: string, accessToken?: string): Promise<FeatureResult<T>> {
  const response = await fetch(path, {
    method: 'POST',
    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : undefined,
  });
  if (!response.ok) {
    throw new Error(`Analysis request failed (${response.status}).`);
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
