export interface PlanningTerm {
  key: string;
  id: string | null;
  label: string;
  year: number;
  season: string;
  sequence: number | null;
  start_date: string | null;
  end_date: string | null;
  enrolled: boolean;
  is_upcoming: boolean;
}

export interface PlannedCourse {
  id: string;
  term_id: string | null;
  course_code: string;
  title: string | null;
  credit_hours: number | null;
  catalog_course_id: string | null;
  created_at: string | null;
  kind: 'planned';
}

export interface CatalogSearchResult {
  id: string;
  code: string;
  title: string;
  department: string | null;
  course_level: number | null;
  credit_min: number | null;
  credit_max: number | null;
}

export type TermStatus = 'upcoming' | 'in_progress' | 'past' | 'unknown';

export interface TermsPayload {
  terms: PlanningTerm[];
  upcoming_term_key: string | null;
}

export interface NormalizedTerms { ok: boolean; terms: PlanningTerm[]; upcomingTermKey: string | null }
export interface NormalizedPlanned { ok: boolean; plannedCourses: PlannedCourse[] }
export interface NormalizedSearch { ok: boolean; results: CatalogSearchResult[] }

export declare const TERMS_URL: string;
export declare const PLANNED_COURSES_URL: string;
export declare const CATALOG_SEARCH_URL: string;
export declare const SEASON_ORDER: Record<string, number>;
export declare const UNKNOWN_SEASON_ORDINAL: number;
export declare const MIN_SEARCH_LENGTH: number;
export declare const SEARCH_DEBOUNCE_MS: number;
export declare const TERM_STATUS_LABELS: Record<TermStatus, string>;

export declare function seasonOrdinal(season: string): number;
export declare function plannedRemoveUrl(id: string): string;
export declare function plannedListUrl(termId: string | null | undefined): string;
export declare function catalogSearchUrl(query: string): string;
export declare function sortTerms(terms: PlanningTerm[]): PlanningTerm[];
export declare function pickDefaultTermKey(payload: Partial<TermsPayload> | null | undefined): string | null;
export declare function termStatus(term: PlanningTerm | null | undefined, today: Date): TermStatus;
export declare function parseDate(value: string | null | undefined): Date | null;
export declare function formatTermDates(term: PlanningTerm | null | undefined): string | null;
export declare function termCourseGroups<R extends { term_id: string | null }>(
  termId: string | null,
  courseRecords: R[],
  plannedCourses: PlannedCourse[],
): { records: R[]; planned: PlannedCourse[] };
export declare function plannedCodes(plannedCourses: PlannedCourse[]): Set<string>;
export declare function formatCredits(min: number | null, max: number | null): string | null;
export declare function normalizeTermsPayload(status: number, body: unknown): NormalizedTerms;
export declare function normalizePlannedPayload(status: number, body: unknown): NormalizedPlanned;
export declare function normalizeSearchPayload(status: number, body: unknown): NormalizedSearch;
