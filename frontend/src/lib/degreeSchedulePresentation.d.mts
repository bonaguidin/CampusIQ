// Types for degreeSchedulePresentation.mjs. The implementation is plain .mjs
// so the existing `node --test tests/` runner can import it directly; this
// file is what lets TS callers under src/ consume it with full checking.

import type {
  DegreeScheduleResult,
  DegreeScheduleResponse,
  RequirementCandidate,
  RequirementDecisionState,
  TermPlan,
} from '../api/degreeSchedule.mjs';

export declare function displayTermKey(termKey: string): string;

export declare function formatCredits(value: number): string;

export declare function termPresentation(
  terms: TermPlan[],
): Array<TermPlan & { displayName: string; totalLabel: string }>;

export type DegreeScheduleContentState = 'skipped' | 'infeasible' | 'empty' | 'scheduled';

export declare function degreeScheduleContentState(result: DegreeScheduleResponse): DegreeScheduleContentState;

export declare function nextPlannedTerm(
  schedule: DegreeScheduleResponse | null,
): (TermPlan & { displayName: string; totalLabel: string }) | null;

export declare function adviserReviewCount(schedule: DegreeScheduleResponse | null): number | null;

export interface DegreeScheduleDecisionPresentation {
  requirementGroupId: string;
  requirementName: string;
  state: Exclude<RequirementDecisionState, 'AUTO_SELECTED'>;
  selectedCandidateId: string | null;
  candidates: RequirementCandidate[];
  validOptionLabel: string;
}

export interface DegreeScheduleDecisionsPresentation {
  decisions: DegreeScheduleDecisionPresentation[];
  legacyRequirements: DegreeScheduleResult['unscheduled'];
}

export declare function buildDegreeScheduleDecisions(
  schedule: DegreeScheduleResponse | null,
): DegreeScheduleDecisionsPresentation;
