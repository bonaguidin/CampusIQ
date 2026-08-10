import type { ReviewSection } from './resumeApi.mjs';

export interface TranscriptRepeatExclusion {
  excluded_from_gpa: true;
  reason: 'repeat_replacement';
  superseded_by_id: string;
  superseded_by: { id: string; course_code: string; letter_grade: string | null; term_id: string | null } | null;
  still_counts_toward_earned_hours: boolean;
}
export interface TranscriptRecord {
  id: string;
  course_code: string;
  title: string | null;
  credit_hours: string | number;
  letter_grade: string | null;
  status: 'completed' | 'in_progress';
  term_id: string | null;
  catalog_course_id: string | null;
  counts_toward_credit: boolean;
  counts_toward_gpa: boolean;
  credit_type: 'resident' | 'transfer' | 'exam' | 'dual_enrollment';
  source: string;
  needs_catalog_review: boolean;
  repeat_exclusion: TranscriptRepeatExclusion | null;
}
export interface TranscriptTerm { id: string; label: string; year: number; season: string; sequence: number; institution_id: string }
export interface TranscriptInstitution { id: string; name: string }
export interface TranscriptFailure { ok: false; kind: string; message: string }

/** Arithmetic cross-check: printed term totals vs. totals computed from rows. */
export interface TranscriptCrossCheckMismatch {
  term_label: string;
  field: string;
  printed: number | null;
  computed: number | null;
  difference: number | null;
}
export interface TranscriptCrossCheck {
  ok: boolean;
  termsChecked: number;
  termsSkipped: number;
  mismatches: TranscriptCrossCheckMismatch[];
}
export interface TranscriptCatalogReport {
  matched: number;
  unmatched: number;
  misses: unknown[];
}
export type TranscriptReviewResult = (TranscriptFailure | { ok: true; kind: 'ok'; message: string }) & { records: TranscriptRecord[]; terms: TranscriptTerm[]; institutions: TranscriptInstitution[]; excludedByRepeat: TranscriptRecord[]; pendingCatalogReview: number };
export type TranscriptUploadResult = (TranscriptFailure | { ok: true; kind: 'ok'; message: string }) & { rejected: unknown[]; warnings: string[]; inserted: number; crossCheck: TranscriptCrossCheck; catalog: TranscriptCatalogReport };
export type TranscriptPatchResult = (TranscriptFailure | { ok: true; kind: 'ok'; message: string }) & { record: TranscriptRecord | null };
export type TranscriptConfirmResult = (TranscriptFailure | { ok: true; kind: 'ok'; message: string }) & { confirmed: number; repeats: unknown };
export const TRANSCRIPT_UPLOAD_URL: string;
export const TRANSCRIPT_REVIEW_URL: string;
export const TRANSCRIPT_CONFIRM_URL: string;
export const TRANSCRIPT_FIELDS: string[];
export const COURSE_STATUS_VALUES: readonly ['completed', 'in_progress'];
export const TRANSCRIPT_SECTION: ReviewSection;
export const TRANSCRIPT_SECTIONS: Record<'course_records', ReviewSection>;
export function transcriptEditUrl(id: string): string;
export function detailErrorCode(detail: unknown): string | null;
export function detailExtractionStatus(detail: unknown): string | null;
export function parseCreditHours(value: unknown): number | null;
export function formatCreditHours(value: unknown): string | null;
export function canonicalTranscriptValue(fieldName: string, value: unknown): unknown;
export function transcriptChangedFields(
  original: Record<string, unknown> | null | undefined,
  draft: Record<string, unknown> | null | undefined,
): Record<string, unknown>;
export function transcriptFieldChanged(
  original: Record<string, unknown> | null | undefined,
  draft: Record<string, unknown> | null | undefined,
  fieldName: string,
): boolean;
export function normalizeTranscriptReview(status: number, body: unknown): TranscriptReviewResult;
export function normalizeTranscriptUpload(status: number, body: unknown): TranscriptUploadResult;
export function normalizeTranscriptPatch(status: number, body: unknown): TranscriptPatchResult;
export function normalizeTranscriptConfirm(status: number, body: unknown): TranscriptConfirmResult;
