/**
 * Page-level signal that a confirm is in flight.
 *
 * WHY THIS EXISTS BEYOND THE COMMIT BAR'S "Saving…" LABEL. The bar's disabled
 * button was the only feedback during confirm, and the confirm request can run
 * 20-50s against a cold-started backend (Render spins the free tier down after
 * 15 min idle). For that whole window the review page sat at full opacity with
 * every field still looking editable, which reads as a frozen tab rather than
 * as work in progress. This dims the content and says how long it may take.
 *
 * Rendered from CommitBar rather than from each review screen: CommitBar is
 * the one component both the resume and transcript flows already share, so a
 * single call site is what guarantees the two flows cannot drift apart here.
 *
 * Sits BELOW the commit bar in z-order (see .rv-confirming in index.css), so
 * the bar's own "Saving…" state stays crisp and legible on top of the dim
 * instead of being greyed out along with the content behind it.
 */
export function ConfirmingOverlay({ confirming }: { confirming: boolean }) {
  if (!confirming) return null;

  return (
    // role="status" + aria-live="polite", never role="alert": this is progress,
    // not a problem, and an assertive announcement would interrupt a screen
    // reader mid-sentence to say nothing has gone wrong.
    <div className="rv-confirming" role="status" aria-live="polite">
      <div className="rv-confirming-panel">
        <div className="spinner" />
        <p className="rv-confirming-title">Saving your record</p>
        <p className="rv-confirming-note">
          This can take up to a minute if the server is waking up.
        </p>
      </div>
    </div>
  );
}
