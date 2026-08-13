import { createContext, useContext } from 'react';

/**
 * A request to go and answer one profile detail, where it is read.
 *
 * WHAT THIS REPLACED AND WHY. This context used to carry a whole
 * `{ feature, missingFields, trigger }` payload into a modal, because the
 * answer lived somewhere the student was not: a dialog that covered the page
 * stating the gap, listed all five fields whether or not they were the one
 * asked about, and put the page's own copy of that data behind an overlay. The
 * fields are now editable in place, so the only thing left to carry is WHICH
 * field -- the surface that owns it already knows how to render and save it.
 *
 * `feature` survives only as context for the copy ("needed for FIT"); nothing
 * routes on it. `trigger` is kept so a caller can be returned to where it came
 * from, and because AnalysisPanel already has the element to hand.
 */
export interface ProfileFieldRequest {
  /** The dotted path from base.py. Matched against `data-profile-field`. */
  path: string;
  feature?: string;
  trigger?: HTMLElement;
}

export const ProfileCompletionContext = createContext<
  ((request: ProfileFieldRequest) => void) | null
>(null);

/**
 * The handler that reveals a field, or null outside a provider.
 *
 * NULL IS A SUPPORTED ANSWER, not a bug to guard against. The demo dashboard
 * and the professor-comment panel render AnalysisPanel outside this provider
 * and have no inline fields to scroll to, so they fall back to the
 * /profile/complete deep link. That fallback is why this returns the handler
 * rather than throwing.
 */
export function useProfileFieldRequest() {
  return useContext(ProfileCompletionContext);
}
