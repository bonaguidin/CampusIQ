// Types for processingStages.mjs. The implementation is plain .mjs so the
// existing `node --test tests/` runner can import it directly; this file is
// what lets TS callers under src/ consume it with full checking.

export type ProcessingKind = 'resume' | 'transcript';

export interface ProcessingStage {
  label: string;
  detail: string;
}

export declare const STAGE_SCHEDULE: readonly number[];
export declare const RESUME_STAGES: readonly ProcessingStage[];
export declare const TRANSCRIPT_STAGES: readonly ProcessingStage[];
export declare const RESUME_TRUST_NOTE: string;
export declare const BUSY_LABEL: Record<ProcessingKind, string>;

export declare function stagesFor(kind: ProcessingKind): readonly ProcessingStage[];
export declare function stageIndexAt(elapsedMs: unknown, schedule?: readonly number[]): number;
export declare function stageTimeouts(schedule?: readonly number[]): number[];
