// What the upload screens SAY while a parse is in flight, and when they say it.
//
// THE HONESTY CONSTRAINT THAT SHAPES ALL OF THIS. The backend exposes no
// progress events for /resume/upload or /transcript/upload -- one request goes
// out, one response comes back, and nothing in between is observable. So a
// percentage here would be a number we invented, and a student watching "48%"
// would be reading a fact about a setTimeout, not about their document. These
// stages are therefore explicitly PRESENTATIONAL: they describe what the server
// is doing in the order it does it, paced by elapsed time, and they are never
// consulted to decide whether anything finished. The response is the only
// authority on that, which is why nothing in this module returns "done".
//
// WHY ELAPSED-TIME THRESHOLDS RATHER THAN A TIMER CHAIN. A pure function of
// elapsed milliseconds is checkable without a clock, cannot drift, and makes
// the two properties that actually matter -- monotonic, and clamped at the last
// stage -- provable in a unit test rather than observed in a browser.
//
// The thresholds are tuned to a parse that typically runs a few seconds (both
// endpoints do a text extraction followed by a model call). They are NOT a
// prediction of duration: a fast response cuts them off wherever it lands, and
// a slow one simply rests on the final stage.

/** Elapsed-ms at which each stage index becomes current. Strictly ascending. */
export const STAGE_SCHEDULE = [0, 900, 2200, 4000];

export const RESUME_STAGES = [
  { label: 'Uploading your resume…', detail: 'Sending your file securely.' },
  { label: 'Reading your resume…', detail: 'Pulling the text out of your document.' },
  {
    label: 'Extracting experience, projects, and certifications…',
    detail: 'Identifying roles, dates, skills, and credentials.',
  },
  { label: 'Preparing your review…', detail: 'Laying out everything we read for you to check.' },
];

export const TRANSCRIPT_STAGES = [
  { label: 'Uploading your transcript…', detail: 'Sending your file securely.' },
  { label: 'Reading your transcript…', detail: 'Pulling the text out of your document.' },
  {
    label: 'Extracting courses and grades…',
    detail: 'Identifying terms, course codes, credit hours, and grades.',
  },
  { label: 'Preparing your review…', detail: 'Laying out every course for you to check.' },
];

/** The line that must survive from the old upload copy: nothing is saved yet. */
export const TRUST_NOTE = {
  resume: 'You’ll review everything before it is saved to your profile.',
  transcript: 'You’ll review every course before it is added to your academic record.',
};

/** The button's active label. Concise, and never the only signal. */
export const BUSY_LABEL = {
  resume: 'Processing resume…',
  transcript: 'Processing transcript…',
};

/** @param {'resume' | 'transcript'} kind */
export function stagesFor(kind) {
  return kind === 'transcript' ? TRANSCRIPT_STAGES : RESUME_STAGES;
}

/**
 * The stage index current at `elapsedMs`.
 *
 * Monotonic and CLAMPED: past the last threshold it stays on the last stage
 * forever rather than wrapping. A cycle back to "Uploading…" after four seconds
 * would tell the student the work restarted, which is both false and alarming
 * on exactly the slow requests where they are most anxious.
 *
 * @param {unknown} elapsedMs
 * @param {readonly number[]} [schedule]
 */
export function stageIndexAt(elapsedMs, schedule = STAGE_SCHEDULE) {
  const elapsed = typeof elapsedMs === 'number' && Number.isFinite(elapsedMs) ? elapsedMs : 0;
  let index = 0;
  for (let i = 0; i < schedule.length; i += 1) {
    if (elapsed >= schedule[i]) index = i;
  }
  return index;
}

/**
 * Delays, from the moment work starts, at which a re-render must be scheduled.
 * Excludes stage 0, which is current immediately and needs no timer.
 *
 * @param {readonly number[]} [schedule]
 */
export function stageTimeouts(schedule = STAGE_SCHEDULE) {
  return schedule.slice(1);
}
