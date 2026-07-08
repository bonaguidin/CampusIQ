// Bridge to CampusIQ_career/api.py — the FastAPI wrapper around orchestrator.run_feature().
// Student identity here is the dashboard slug (e.g. "jordanReyes"), matching
// dataAdapter.ts's `/data/student_${slug}.json` convention.

import type {
  FeatureResult,
  FitAnalysisData,
  GapAnalysisData,
  ProfessorCommentAnalysisData,
} from '../types/analysis';

async function postAnalysis<T>(path: string): Promise<FeatureResult<T>> {
  const response = await fetch(path, { method: 'POST' });
  if (!response.ok) {
    throw new Error(`Analysis request failed (${response.status}).`);
  }
  return (await response.json()) as FeatureResult<T>;
}

export function analyzeGap(slug: string): Promise<FeatureResult<GapAnalysisData>> {
  return postAnalysis(`/api/students/${encodeURIComponent(slug)}/analyze/gap`);
}

export function analyzeFit(slug: string): Promise<FeatureResult<FitAnalysisData>> {
  return postAnalysis(`/api/students/${encodeURIComponent(slug)}/analyze/fit`);
}

export function analyzeProfessorComments(
  slug: string,
): Promise<FeatureResult<ProfessorCommentAnalysisData>> {
  return postAnalysis(`/api/students/${encodeURIComponent(slug)}/analyze/professor-comments`);
}
