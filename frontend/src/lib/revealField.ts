/**
 * Bring a field into view, flag it, then focus it.
 *
 * THE SAME MOVE THE REVIEW SCREENS ALREADY MAKE. CareerReview's `jumpToGap`
 * and TranscriptReview's row jump are this exact sequence, and the ordering in
 * both is deliberate rather than incidental:
 *
 *   - the scroll respects prefers-reduced-motion, because a page that jumps
 *     under someone who asked it not to is worse than no animation at all;
 *   - the flag is a brief highlight, removed after 500ms, so the student can
 *     see WHICH thing the page just moved to rather than having to work it out
 *     from the scroll position;
 *   - focus happens LAST and on a delay, so the browser does not fight its own
 *     smooth scroll -- focusing mid-scroll makes the viewport jump to the
 *     element and abandon the animation.
 *
 * `focusTarget` is a callback rather than an element because the thing worth
 * focusing usually does not exist yet at call time: revealing a field also
 * opens its editor, and the input to focus is rendered by that state change.
 * Resolving it inside the timeout means it is queried after React has
 * committed.
 */
export function revealField(node: HTMLElement, focusTarget?: () => HTMLElement | null): void {
  const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  node.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'center' });
  node.classList.add('cp-field-flag');
  window.setTimeout(() => { node.classList.remove('cp-field-flag'); }, 500);
  window.setTimeout(() => { focusTarget?.()?.focus(); }, reduce ? 0 : 320);
}
