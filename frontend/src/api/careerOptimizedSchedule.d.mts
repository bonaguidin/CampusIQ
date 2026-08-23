// Types for careerOptimizedSchedule.mjs. The implementation is plain .mjs so
// the existing `node --test tests/` runner can import it directly; this file
// is what lets TS callers under src/ consume it with full checking.

import type { ScheduleResult } from './degreeSchedule.mjs';

export type CareerOptimizationStatus = 'OPTIMIZED' | 'PARTIAL' | 'FALLBACK' | 'SKIPPED';
export type CareerSelectionBasis = 'CAREER_RANKED' | 'ACADEMIC_DEFAULT';
export type CareerOptimizationCacheStatus = 'HIT' | 'MISS' | 'BYPASSED';

export interface RankedRequirementCandidate {
  candidate_id: string;
  rank: number;
  ranking_reason: string;
  skill_alignment_explanation: string;
}

export interface RequirementCandidateRanking {
  requirement_group_id: string;
  ranked_candidates: RankedRequirementCandidate[];
}

export interface RequirementRankingFailure {
  requirement_group_id: string;
  requirement_name: string;
  error_code: string;
  detail: string;
}

export interface CareerOptimizedScheduleResponse {
  feature: 'CAREER_OPTIMIZED_SCHEDULE';
  status: CareerOptimizationStatus;
  selection_basis: CareerSelectionBasis;
  target_role: string | null;
  fingerprint: string | null;
  generated_at: string;
  cache_status: CareerOptimizationCacheStatus;
  academic_schedule: ScheduleResult;
  optimized_schedule: ScheduleResult;
  requirement_rankings: RequirementCandidateRanking[];
  ranking_failures: RequirementRankingFailure[];
  ranking_prompt_version: string;
  resolved_model: string;
  summary: string | null;
}

export interface CareerOptimizeScheduleRequest {
  target_role?: string;
  force_refresh?: boolean;
}

export declare function isCareerOptimizedScheduleResponse(value: unknown): value is CareerOptimizedScheduleResponse;

export declare function fetchCareerOptimizedSchedule(
  token: string,
  request?: CareerOptimizeScheduleRequest,
): Promise<CareerOptimizedScheduleResponse>;
