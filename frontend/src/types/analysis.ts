// Mirrors CampusIQ_career/features/gap.py and academic.py's `output_contract`
// dicts. Confirmed against real (non-mocked) DeepSeek R1 output — see
// /tmp/career_result.json and /tmp/academic_result.json from the validation
// run. academic.py's shape matched on the first real call; gap.py's
// must_have_gaps/nice_to_have_gaps did not (contract said bare string[],
// real output was structured objects) and has been corrected here to match.

export type FeatureStatus = 'success' | 'skipped' | 'failed';

export interface FeatureResult<T> {
  feature: string;
  status: FeatureStatus;
  summary: string;
  data: T;
  errors: string[];
}

// ── GAP (readiness check) — gap.py output_contract ──────────────────────────

export interface GapMustHaveGap {
  gap: string;
  why_it_matters?: string;
  why_it_helps?: string;
  how_to_close: string;
}

export interface GapAnalysisData {
  readiness_score: number;
  strengths: string[];
  must_have_gaps: GapMustHaveGap[];
  nice_to_have_gaps: GapMustHaveGap[];
  recommended_next_steps: string[];
}

// ── FIT (role-fit check) — fit.py output_contract ───────────────────────────
// Confirmed against real (non-mocked) DeepSeek R1 output — see
// /tmp/career_result.json from the validation run.

export type FitLevel = 'high' | 'medium' | 'low';

export interface FitRoleMatch {
  role: string;
  fit_level: FitLevel;
  rationale: string;
  supporting_signals: string[];
  missing_signals: string[];
}

export interface FitAnalysisData {
  role_matches: FitRoleMatch[];
  overall_fit_summary: string;
}

// ── SHIFT (trend-aware guidance) — shift.py output_contract ─────────────────
// Types match ShiftRunner.output_contract field-for-field (task_shifts,
// durable_skills, adjacent_paths, ai_fluency_guidance) — not yet confirmed
// against real (non-mocked) model output, same caveat as GAP.

export interface ShiftTaskShift {
  task: string;
  changing: string;
  meaning: string;
}

export interface ShiftDurableSkill {
  task: string;
  reason: string;
}

export interface ShiftAdjacentPath {
  path: string;
  relevance: string;
  driver: string;
}

export interface ShiftAnalysisData {
  role_evolution_summary: string;
  task_shifts: ShiftTaskShift[];
  durable_skills: ShiftDurableSkill[];
  adjacent_paths: ShiftAdjacentPath[];
  ai_fluency_guidance: string[];
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
