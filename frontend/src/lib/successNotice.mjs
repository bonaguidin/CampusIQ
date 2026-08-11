// The one place that decides what a completed resume/transcript confirmation
// says, and the one place that decides whether a piece of router state is a
// success notice at all.
//
// WHY A SHARED MODULE FOR THREE STRINGS. The two flows previously each ended on
// their own terminal screen with their own copy, and the copy drifted precisely
// because it was written twice. The screens are gone; the wording must not be
// allowed to fork again on the way out. Keeping it here also keeps it testable
// without a browser -- this is plain .mjs so `node --test` can import it
// directly, same arrangement as resumeApi.mjs/signupRules.mjs.
//
// WHY THE COUNT IS OPTIONAL. /transcript/confirm reports `confirmed`, the
// number of course records it actually wrote, and that is a fact worth telling
// the student. But a zero or a missing field is NOT a number to render -- it is
// an absence -- so the generic sentence is the floor, never "0 courses added".
// The resume side has no equivalent trustworthy count to show (`total_confirmed`
// counts rows across four tables, which is not a quantity a student thinks in),
// so it does not try.

export const TRANSCRIPT_SUCCESS_MESSAGE = 'Transcript saved and added to your academic record.';
export const RESUME_SUCCESS_MESSAGE = 'Resume saved — your career profile has been updated.';

/** @param {unknown} confirmedCount */
export function transcriptSuccessMessage(confirmedCount) {
  const count = typeof confirmedCount === 'number' && Number.isFinite(confirmedCount)
    ? Math.trunc(confirmedCount)
    : 0;
  if (count <= 0) return TRANSCRIPT_SUCCESS_MESSAGE;
  return count === 1
    ? 'Transcript saved — 1 course added to your academic record.'
    : `Transcript saved — ${String(count)} courses added to your academic record.`;
}

/**
 * The router state a successful transcript confirmation carries to /dashboard.
 * @param {unknown} confirmedCount
 */
export function transcriptSuccessState(confirmedCount) {
  return { success: { type: 'transcript', message: transcriptSuccessMessage(confirmedCount) } };
}

/** The router state a successful resume confirmation carries to /dashboard. */
export function resumeSuccessState() {
  return { success: { type: 'resume', message: RESUME_SUCCESS_MESSAGE } };
}

/**
 * Read a success notice out of arbitrary router state.
 *
 * Deliberately total and defensive: `location.state` is whatever the previous
 * entry put there, including nothing at all on a direct visit to /dashboard,
 * and including whatever a restored history entry preserved across a reload.
 * Anything that is not exactly the shape written above reads as "no notice".
 *
 * @param {unknown} state
 * @returns {{ type: 'transcript' | 'resume', message: string } | null}
 */
export function readSuccessNotice(state) {
  if (!state || typeof state !== 'object') return null;
  const { success } = /** @type {{ success?: unknown }} */ (state);
  if (!success || typeof success !== 'object') return null;
  const { type, message } = /** @type {{ type?: unknown, message?: unknown }} */ (success);
  if (type !== 'transcript' && type !== 'resume') return null;
  if (typeof message !== 'string' || message.trim() === '') return null;
  return { type, message };
}
