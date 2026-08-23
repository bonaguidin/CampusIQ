// Types for requirementSatisfaction.mjs. The implementation is plain .mjs so
// the existing `node --test tests/` runner can import it directly; this file
// is what lets TS callers under src/ consume it with full checking.

import type { FeatureResult } from '../types/analysis';

export type RequirementGroupStatus = 'SATISFIED' | 'IN_PROGRESS' | 'NOT_STARTED' | 'MANUAL_REVIEW';

// Mirrors GradusIQ_career/course_discovery/requirement_satisfaction.py's
// RequirementGroupResult. children is the same shape recursively -- there is
// no depth limit on either side.
export interface RequirementGroupResult {
  id: string;
  coursedog_rule_id: string;
  name: string;
  group_type: string;
  status: RequirementGroupStatus;
  detail: string | null;
  matched_course_codes: string[];
  children: RequirementGroupResult[];
}

// The route's success payload is a bare RequirementSatisfactionResult, not a
// FeatureResult -- see api.py's get_me_requirement_satisfaction: evaluation is
// a pure, sub-second computation with no AI call to distinguish "ran and
// failed" from "ran fine", so there is no status field to check on this path.
// Only the "no program for this student yet" precondition uses FeatureResult
// (status: 'skipped'), the same shape every other analysis uses for that case.
export interface RequirementSatisfactionSuccess {
  student_id: string;
  program_id: string;
  groups: RequirementGroupResult[];
}

export type RequirementSatisfactionSkipped = FeatureResult<Record<string, never>>;

export type RequirementSatisfactionResponse = RequirementSatisfactionSuccess | RequirementSatisfactionSkipped;

export declare function isSkippedRequirementSatisfaction(
  result: RequirementSatisfactionResponse,
): result is RequirementSatisfactionSkipped;

export declare function fetchRequirementSatisfaction(token: string): Promise<RequirementSatisfactionResponse>;
