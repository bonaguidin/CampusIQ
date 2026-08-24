// Types for degreeSchedule.mjs. The implementation is plain .mjs so the
// existing `node --test tests/` runner can import it directly; this file is
// what lets TS callers under src/ consume it with full checking.

import type { FeatureResult } from '../types/analysis';
import type { AnalysisIdentity } from './analysisApi.mjs';

export interface ScheduledCourse {
  course_code: string;
  credit_hours: number;
  requirement_group_id: string;
  limitations: string[];
}

export interface TermPlan {
  term_key: string;
  courses: ScheduledCourse[];
  total_credit_hours: number;
}

export type UnscheduledReason = 'SELECTION_DEFERRED' | 'FREEFORM_MANUAL_REVIEW';

export interface UnscheduledRequirement {
  requirement_group_id: string;
  name: string;
  reason: UnscheduledReason;
}

export interface ScheduleFailure {
  error_class: string;
  safe_message: string;
}

export interface ScheduleResult {
  student_id: string;
  program_id: string;
  terms: TermPlan[];
  unscheduled: UnscheduledRequirement[];
  status: 'SCHEDULED' | 'ERROR';
  failure: ScheduleFailure | null;
}

export type DegreeScheduleSkipped = FeatureResult<Record<string, never>>;
export type DegreeScheduleResponse = ScheduleResult | DegreeScheduleSkipped;

export declare function isSkippedDegreeSchedule(result: DegreeScheduleResponse): result is DegreeScheduleSkipped;

export declare function fetchDegreeSchedule(identity: AnalysisIdentity): Promise<DegreeScheduleResponse>;
