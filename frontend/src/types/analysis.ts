// PROVISIONAL — mirrors CampusIQ_career/features/gap.py and academic.py's
// `output_contract` dicts, which describe the JSON shape requested from the
// model but have not yet been confirmed against a real (non-mocked) AI
// response — see the credit-blocked validation run. Free models in
// particular can drift from a requested JSON contract. Revisit these types
// once a real call has been observed end to end.

export type FeatureStatus = 'success' | 'skipped' | 'failed';

export interface FeatureResult<T> {
  feature: string;
  status: FeatureStatus;
  summary: string;
  data: T;
  errors: string[];
}

// ── GAP (readiness check) — gap.py output_contract ──────────────────────────

export interface GapAnalysisData {
  readiness_score: number;
  strengths: string[];
  must_have_gaps: string[];
  nice_to_have_gaps: string[];
  recommended_next_steps: string[];
}

// ── PROFESSOR_COMMENTS (academic.py output_contract) ─────────────────────────

export type ThemeCategory = 'strength' | 'concern' | 'praise' | 'flag';

export interface ThemeReference {
  course_code: string;
  course_name: string;
  paraphrase: string;
}

export interface Theme {
  theme: string;
  category: ThemeCategory;
  summary: string;
  supporting_references: ThemeReference[];
}

export interface ProfessorCommentAnalysisData {
  themes: Theme[];
  overall_summary: string;
}
