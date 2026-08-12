// Types for resumeApi.mjs. The implementation is plain .mjs so the existing
// `node --test tests/` runner can import it directly; this file is what lets
// TS callers under src/ consume it with full checking.

export declare const UPLOAD_URL: string;
export declare const REVIEW_URL: string;
export declare const CONFIRM_URL: string;

/** Synthetic status meaning the client stopped waiting. Never a real HTTP code. */
export declare const REQUEST_TIMEOUT_STATUS: number;
export declare const CONFIRM_TIMEOUT_MS: number;

export type ChildTable = 'certifications' | 'work_experience' | 'projects';
export type SectionKey = 'career_profile' | ChildTable;

export declare const CHILD_TABLES: readonly ChildTable[];
export declare const ALL_SECTIONS: readonly SectionKey[];
export declare const CERT_STATUS_VALUES: readonly string[];

export declare function reviewEditUrl(table: string, id: string): string;

/**
 * `number` is part of the review system's permanent vocabulary, not a
 * resume-only addition: transcript review needs it for credit_hours, where a
 * silently coerced value changes a GPA. No resume section uses it today; the
 * renderer and validation support it so transcript review does not have to
 * retrofit the type later.
 */
export type FieldType = 'text' | 'textarea' | 'list' | 'status' | 'number';

export interface ReviewField {
  name: string;
  label: string;
  type: FieldType;
}

export interface ReviewSection {
  label: string;
  singular: string;
  titleField?: string;
  fields: readonly ReviewField[];
  /**
   * Explicit subtitle fields, in order. Omitted by every resume section, which
   * keeps the derived "first two filled non-title fields" behaviour. Named by
   * the transcript section, whose useful subtitle (credits · grade) is not the
   * first two fields in declaration order.
   */
  subtitleFields?: readonly string[];
}

export declare const REVIEW_SECTIONS: Record<SectionKey, ReviewSection>;
export declare function editableFieldNames(table: string): string[];

export declare function detailToText(detail: unknown, fallback?: string): string;
export declare function detailExtractionStatus(detail: unknown): string | null;

export interface TableCounts {
  inserted: number;
  skipped_duplicate: number;
}

export type WrittenCounts = Record<ChildTable, TableCounts>;

export interface WrittenTotals {
  inserted: number;
  skipped_duplicate: number;
  total: number;
}

export declare const EMPTY_WRITTEN: WrittenCounts;
export declare function normalizeWritten(written: unknown): WrittenCounts;
export declare function writtenTotals(written: unknown): WrittenTotals;

export interface ExtractionInfo {
  status: string;
  page_count: number | null;
}

export interface CareerProfileOutcome {
  outcome: 'created' | 'already_existed_untouched';
  id: string | null;
}

export type UploadKind =
  | 'ok'
  | 'not_a_resume'
  | 'unparseable'
  | 'parse_failed'
  | 'empty'
  | 'extraction_failed'
  | 'unsupported_format'
  | 'invalid'
  | 'file_too_large'
  | 'bad_upload'
  | 'no_student_profile'
  | 'unauthenticated'
  | 'forbidden'
  | 'rate_limited'
  | 'ai_busy'
  | 'backend_unavailable'
  | 'not_configured'
  | 'unknown';

export interface NormalizedUpload {
  ok: boolean;
  kind: UploadKind;
  message: string;
  httpStatus: number;
  extraction: ExtractionInfo | null;
  warnings: string[];
  model: string | null;
  written: WrittenCounts;
  totals: WrittenTotals;
  careerProfile: CareerProfileOutcome | null;
  academics: ResumeAcademicFacts;
  errors: string[];
}

export interface ResumeAcademicFacts {
  major_current: string | null;
  expected_graduation: string | null;
}

export declare function normalizeUploadResponse(
  httpStatus: number,
  body: unknown,
): NormalizedUpload;

export interface ReviewRow {
  id: string;
  source: string | null;
  [field: string]: unknown;
}

export interface ReviewSections {
  career_profile: ReviewRow | null;
  certifications: ReviewRow[];
  work_experience: ReviewRow[];
  projects: ReviewRow[];
}

export declare const EMPTY_REVIEW: ReviewSections;

export interface NormalizedReview {
  ok: boolean;
  kind: string;
  message: string;
  httpStatus: number;
  sections: ReviewSections;
  pendingCount: number;
}

export declare function normalizeReviewResponse(
  httpStatus: number,
  body: unknown,
): NormalizedReview;

export declare function countPending(sections: Partial<ReviewSections> | null): number;

export type PatchKind =
  | 'ok'
  | 'not_found'
  | 'already_confirmed'
  | 'conflict'
  | 'invalid'
  | 'unauthenticated'
  | 'forbidden'
  | 'rate_limited'
  | 'ai_busy'
  | 'backend_unavailable'
  | 'not_configured'
  | 'unknown';

export interface NormalizedPatch {
  ok: boolean;
  kind: PatchKind;
  message: string;
  httpStatus: number;
  row: ReviewRow | null;
}

export declare function normalizePatchResponse(httpStatus: number, body: unknown): NormalizedPatch;

export type ConfirmedCounts = Record<SectionKey, number>;

export declare function confirmedToSingular(confirmed: unknown): ConfirmedCounts;

export interface NormalizedConfirm {
  ok: boolean;
  kind: string;
  message: string;
  httpStatus: number;
  scope: string | null;
  confirmed: ConfirmedCounts;
  totalConfirmed: number;
}

export declare function normalizeConfirmResponse(
  httpStatus: number,
  body: unknown,
): NormalizedConfirm;

export declare function changedFields(
  table: string,
  original: Record<string, unknown> | null,
  draft: Record<string, unknown> | null,
): Record<string, unknown>;

export declare function normalizeFieldValue(value: unknown): unknown;
export declare function parseListInput(text: string): string[];
export declare function formatListInput(value: unknown): string;

// ── review-screen model ─────────────────────────────────────────────────────

export declare function isEmptyValue(value: unknown): boolean;

export declare const GLYPH_READ: '·';
export declare const GLYPH_EDITED: '✎';
export declare const GLYPH_EMPTY: '⌀';

/** null when the field is empty and unchanged (no row is rendered for it). */
export declare function fieldGlyph(
  original: Record<string, unknown> | null,
  draft: Record<string, unknown> | null,
  fieldName: string,
): '·' | '✎' | '⌀' | null;

export declare function entryGaps(table: string, row: Record<string, unknown> | null): string[];
export declare function entryFilled(table: string, row: Record<string, unknown> | null): string[];

export interface CounterRow {
  table: SectionKey;
  original: Record<string, unknown> | null;
  draft: Record<string, unknown> | null;
}

export interface ReviewCounters {
  read: number;
  edited: number;
  gaps: number;
  total: number;
  filledRatio: number;
}

export declare function reviewCounters(rows: readonly CounterRow[] | null): ReviewCounters;

export declare function parseNumberInput(text: unknown): number | null;
export declare function formatNumberInput(value: unknown): string;
