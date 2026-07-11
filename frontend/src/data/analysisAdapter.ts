// Loads cached career-analysis output produced by the Python engine
// (CampusIQ_career/demo/build_demo_cache.py -> frontend/public/data/analysis_<slug>.json).
//
// Additive on purpose: mirrors how dataAdapter loads student_<slug>.json, so
// the demo needs no live backend. To go live later, swap the fetch for a call
// to a real /api/analysis/:slug endpoint — the shape stays the same.

export type FeatureStatus = "success" | "skipped" | "failed";

export interface FeatureResult {
  feature: string; // "FIT" | "GAP" | "SHIFT"
  status: FeatureStatus;
  summary: string;
  data: Record<string, unknown>;
  errors: string[];
}

export interface CareerAnalysis {
  analysis_type: string; // "career"
  status: string; // "success" | "partial_success" | "skipped" | "failed"
  student_id: string | null;
  features_requested: string[];
  results: Record<string, FeatureResult>; // keyed by feature name
  summary: string;
  errors: string[];
}

// Convenience view of a GAP result's data payload (matches GapRunner.output_contract).
export interface GapData {
  readiness_score: number;
  strengths: string[];
  must_have_gaps: string[];
  nice_to_have_gaps: string[];
  recommended_next_steps: string[];
}

const ANALYSIS_BASE = "/data";

/**
 * Fetch cached analysis for a student slug (e.g. "priyaNair").
 * Returns null if no cache file exists yet (feature not run) so callers can
 * render an empty/"run analysis" state instead of crashing.
 */
export async function loadAnalysis(slug: string): Promise<CareerAnalysis | null> {
  try {
    const res = await fetch(`${ANALYSIS_BASE}/analysis_${slug}.json`, {
      cache: "no-store",
    });
    if (!res.ok) return null;
    return (await res.json()) as CareerAnalysis;
  } catch {
    return null;
  }
}

/** Pull a single feature's result out of the analysis bundle. */
export function getFeature(
  analysis: CareerAnalysis | null,
  feature: "FIT" | "GAP" | "SHIFT",
): FeatureResult | null {
  if (!analysis) return null;
  return analysis.results?.[feature] ?? null;
}

/** Typed accessor for GAP data, or null if GAP didn't succeed. */
export function getGapData(analysis: CareerAnalysis | null): GapData | null {
  const gap = getFeature(analysis, "GAP");
  if (!gap || gap.status !== "success") return null;
  return gap.data as unknown as GapData;
}
