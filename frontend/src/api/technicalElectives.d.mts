// Types for technicalElectives.mjs. The implementation is plain .mjs so the
// existing `node --test tests/` runner can import it directly; this file is
// what lets TS callers under src/ consume it with full checking.

import type { FeatureResult } from '../types/analysis';
import type { AnalysisIdentity } from './analysisApi.mjs';

export type TechnicalElectiveEligibility =
  | 'READY'
  | 'PREREQUISITES_PLANNED'
  | 'PREREQUISITES_MISSING';

export interface TechnicalElectiveCandidate {
  course_code: string;
  title: string;
  description: string;
  credit_min: number;
  credit_max: number;
  eligibility: TechnicalElectiveEligibility;
  satisfied_prerequisite_codes: string[];
  planned_prerequisite_codes: string[];
  missing_prerequisite_options: string[][];
  limitations: string[];
  catalog_year: string;
  source_url: string;
  source_last_checked: string;
}

export interface TechnicalElectiveCandidateSuccess {
  student_id: string;
  program_id: string;
  requirement_group_id: string;
  requirement_name: string;
  credits_required: number;
  review_required: boolean;
  institution: 'smu';
  catalog_year: string;
  candidates: TechnicalElectiveCandidate[];
  limitations: Array<
    | 'ADVISER_APPROVAL_REQUIRED'
    | 'TRACK_EXCLUSION_NOT_EVALUATED'
    | 'CROSS_DEPARTMENT_EXCEPTIONS_NOT_INCLUDED'
  >;
  stats: {
    catalog_courses_considered: number;
    cs_3000_plus_courses: number;
    excluded_already_used: number;
    excluded_zero_credit: number;
    excluded_restriction_or_review: number;
    candidate_count: number;
  };
}

export type TechnicalElectiveCandidateResponse =
  | TechnicalElectiveCandidateSuccess
  | FeatureResult<Record<string, never>>;

export declare function isSkippedTechnicalElectives(
  result: TechnicalElectiveCandidateResponse,
): result is FeatureResult<Record<string, never>>;

export declare function fetchTechnicalElectiveCandidates(
  identity: AnalysisIdentity,
): Promise<TechnicalElectiveCandidateResponse>;
