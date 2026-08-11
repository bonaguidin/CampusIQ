import { useProcessingStage } from '../hooks/useProcessingStage';
import { BUSY_LABEL, TRUST_NOTE, stagesFor } from '../lib/processingStages.mjs';
import type { ProcessingKind } from '../lib/processingStages.mjs';

export interface ProcessingStatusProps {
  kind: ProcessingKind;
  /** The file being read. Kept on screen so "what is it working on" is never a
   *  guess -- a bare spinner answers "is it working" and nothing else. */
  fileName: string;
  /** Whether the request is in flight. Owned by the upload screen, not here. */
  active: boolean;
}

/**
 * The in-flight state shared by the resume and transcript uploads.
 *
 * WHY ONE COMPONENT FOR TWO SCREENS THAT LOOK NOTHING ALIKE. The resume upload
 * lives in the centred `login-card` shell and the transcript upload in the
 * editorial `rv-page` one; unifying those is not this phase's business. What
 * IS identical is the thing being communicated -- a file, a stage, a motion
 * cue, and a promise that nothing is saved yet -- and that had no shared home,
 * so the two screens' loading treatments had already drifted to a button label
 * apiece with different wording. This owns the presentation and the timers.
 * The upload request, its result, and its errors stay with the flows.
 *
 * The panel is built from design tokens rather than either shell's classes, so
 * it reads correctly inside both without dragging one screen's identity into
 * the other.
 */
export function ProcessingStatus({ kind, fileName, active }: ProcessingStatusProps) {
  const stage = useProcessingStage(active);
  const stages = stagesFor(kind);
  const current = stages[Math.min(stage, stages.length - 1)];

  if (!active) return null;

  return (
    <div className="dp-panel" data-processing={kind}>
      <p className="dp-file" title={fileName}>
        {fileName}
      </p>

      {/*
        The live region carries the stage text ONLY. The rail and the marker are
        aria-hidden: announcing decoration on every tick would bury the one
        sentence that carries meaning. Polite, never assertive -- this is
        progress, and interrupting a screen reader to report that nothing has
        gone wrong is its own kind of failure.
      */}
      <div className="dp-stage" role="status" aria-live="polite">
        {/* Keyed on the stage so the text re-enters rather than swapping in
            place. Purely a fade; the copy is legible with or without it. */}
        <p className="dp-stage-label" key={stage}>
          <span className="dp-marker" aria-hidden="true" />
          {current.label}
        </p>
        <p className="dp-stage-detail">{current.detail}</p>
      </div>

      {/*
        Indeterminate by construction: a segment that travels the rail and never
        rests at a position. It cannot be read as a percentage because it never
        stops anywhere, which is exactly the claim we are not entitled to make.
      */}
      <div className="dp-rail" aria-hidden="true">
        <span className="dp-rail-run" />
      </div>

      <p className="dp-note">{TRUST_NOTE[kind]}</p>
    </div>
  );
}

/** The active button label for a kind. Co-located so the two never diverge. */
export function processingLabel(kind: ProcessingKind): string {
  return BUSY_LABEL[kind];
}
