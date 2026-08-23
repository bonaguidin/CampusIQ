// Types for careerSchedulePresentation.mjs. The implementation is plain .mjs
// so the existing `node --test tests/` runner can import it directly; this
// file is what lets TS callers under src/ consume it with full checking.

import type {
  CareerOptimizedScheduleResponse,
  CareerOptimizationStatus,
  RequirementCandidateRanking,
} from '../api/careerOptimizedSchedule.mjs';
import type { ScheduleResult } from '../api/degreeSchedule.mjs';

export interface CoursePlacement {
  courseCode: string;
  termKey: string;
}

export interface CareerScheduleChange {
  requirementGroupId: string;
  academicCourses: CoursePlacement[];
  optimizedCourses: CoursePlacement[];
  addedCourseCodes: string[];
  removedCourseCodes: string[];
  movedCourseCodes: string[];
  unchangedCourseCodes: string[];
  careerRanked: boolean;
  candidateId: string | null;
  rankingReason: string | null;
  skillAlignmentExplanation: string | null;
}

export interface CourseTermMove {
  courseCode: string;
  fromTermKey: string;
  toTermKey: string;
}

export interface CareerScheduleComparison {
  changes: CareerScheduleChange[];
  changedChoiceCount: number;
  hasChanges: boolean;
}

export interface CareerOptimizationCopy {
  heading: string;
  message: string;
  tone: 'success' | 'warning' | 'neutral';
}

export declare function compareCareerSchedules(
  academic: ScheduleResult,
  optimized: ScheduleResult,
  rankings: RequirementCandidateRanking[],
): CareerScheduleComparison;

export declare function careerOptimizationCopy(
  status: CareerOptimizationStatus,
  summary: string | null,
): CareerOptimizationCopy;

export declare function careerChangeHeading(change: CareerScheduleChange): string;

export declare function courseTermMoves(change: CareerScheduleChange): CourseTermMove[];

export declare function graduationTimingImpact(academic: ScheduleResult, optimized: ScheduleResult): string;

export declare function careerChangeSummary(comparison: CareerScheduleComparison): string;

export type CareerOptimizationView = 'academic' | 'optimized';
export type CareerOptimizationRunState =
  | { phase: 'idle' }
  | { phase: 'loading' }
  | { phase: 'done'; result: CareerOptimizedScheduleResponse; view: CareerOptimizationView }
  | { phase: 'transport-error'; message: string };

export declare const INITIAL_CAREER_OPTIMIZATION_STATE: CareerOptimizationRunState;

export declare function completedCareerOptimizationState(
  result: CareerOptimizedScheduleResponse,
): CareerOptimizationRunState;
