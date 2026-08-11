// Types for successNotice.mjs. The implementation is plain .mjs so the existing
// `node --test tests/` runner can import it directly; this file is what lets TS
// callers under src/ consume it with full checking.

export type SuccessNoticeType = 'transcript' | 'resume';

export interface SuccessNotice {
  type: SuccessNoticeType;
  message: string;
}

/** The router-state envelope carried from a review screen to /dashboard. */
export interface SuccessNoticeState {
  success: SuccessNotice;
}

export declare const TRANSCRIPT_SUCCESS_MESSAGE: string;
export declare const RESUME_SUCCESS_MESSAGE: string;

export declare function transcriptSuccessMessage(confirmedCount: unknown): string;
export declare function transcriptSuccessState(confirmedCount: unknown): SuccessNoticeState;
export declare function resumeSuccessState(): SuccessNoticeState;
export declare function readSuccessNotice(state: unknown): SuccessNotice | null;
