import type { StudentIntelligenceProfile } from '../types/studentIntelligenceProfile';

/**
 * The profile details that gate an analysis, mirrored for the client.
 *
 * MIRRORED, NOT SHARED -- the same arrangement as majorSentinel.ts, and for
 * the same reason: `required_paths` is Python that never crosses the wire, and
 * the server only names a missing field in a *skipped* analysis result. The
 * checklist has to say what is missing before anything has been run, so it
 * computes the answer here from the profile the dashboard already holds.
 *
 * THE UNION OF GAP, FIT AND SHIFT, LESS THE RESUME-OWNED PATHS. Skills and
 * work experience are required by all three but are parsed from the resume and
 * edited on /resume, so they are not gaps this surface can close -- they route
 * through AnalysisPanel's RESUME_OWNED_PATHS exactly as they already did, and
 * are deliberately absent here rather than duplicated.
 *
 * ai_anxiety_level and major_current are editable on the Career tab and are
 * still NOT here: neither appears in any runner's required_paths, so neither
 * blocks anything, and counting them would tell a student they are missing
 * something that gates nothing.
 *
 * The duplication is not left to good intentions: profileChecklist.test.mjs
 * reads gap.py, fit.py and shift.py, takes that union itself, and fails if it
 * stops matching this list -- including the labels, which come from base.py's
 * FIELD_LABELS so the checklist and a skipped analysis name a field the same
 * way.
 */
export interface ChecklistField {
  /** The dotted path base.py uses. Carried for parity and never rendered. */
  path: string;
  label: string;
}

export const CHECKLIST_FIELDS: ChecklistField[] = [
  { path: 'student.expected_graduation', label: 'Expected graduation' },
  { path: 'student.major_intended', label: 'Intended major' },
  { path: 'career.target_roles', label: 'Target roles' },
  { path: 'career.interests', label: 'Career interests' },
];

/**
 * base.py's `is_missing`, restated.
 *
 * Null is missing, a blank string is missing, an empty list is missing --
 * and NOTHING ELSE IS. A non-blank string counts as answered even when that
 * string is the N/A sentinel, because "I am not switching majors" is an answer
 * to the intended-major question, not the absence of one. A checklist that
 * called it missing would nag a student to re-answer something they had
 * already settled, and FIT would disagree with the nag.
 */
export function isMissingValue(value: unknown): boolean {
  if (value === null || value === undefined) return true;
  if (typeof value === 'string') return value.trim() === '';
  if (Array.isArray(value)) return value.length === 0;
  return false;
}

/**
 * Where each mirrored path lives on the canonical client profile.
 *
 * The dotted paths are the SERVER's shape (`student.` / `career.`), which is
 * not the shape profile_builder hands this client -- expected graduation is on
 * `identity`, the intended major on `academics.summary`. Reconciling the two
 * is this function's whole job, and keeping it in one place is why nothing
 * else in the app has to know that the two shapes differ.
 */
function storedValue(profile: StudentIntelligenceProfile, path: string): unknown {
  switch (path) {
    case 'student.expected_graduation':
      return profile.identity.expected_graduation;
    case 'student.major_intended':
      return profile.academics.summary.major_intended;
    case 'career.target_roles':
      return profile.career.target_roles;
    case 'career.interests':
      return profile.career.interests;
    default:
      return null;
  }
}

/** The gating details this profile has not answered, in checklist order. */
export function missingChecklistFields(profile: StudentIntelligenceProfile): ChecklistField[] {
  return CHECKLIST_FIELDS.filter((field) => isMissingValue(storedValue(profile, field.path)));
}
