/**
 * The continue action for the resume and transcript terminal screens.
 *
 * WHY A SHARED COMPONENT FOR ONE LINK. Both flows' "done" screens previously
 * ended with no way forward at all -- resume told the student to close the tab,
 * transcript said nothing -- and they drifted apart precisely because the copy
 * was written twice. One component is what keeps the two endings identical.
 *
 * WHY A PLAIN ANCHOR AND NOT react-router's <Link>. Two reasons, both about
 * this being a terminal state rather than a step:
 *
 *   1. A full document load is the RIGHT behaviour here. The onboarding flow
 *      is finished and its in-memory state is deliberately discarded; the
 *      dashboard should mount from a clean slate rather than inherit it.
 *   2. Neither terminal screen sits under a Router in the preview harnesses
 *      that both flows are tested through (transcriptPreview.tsx,
 *      resumeRecoveryPreview.tsx mount the flow components bare). A <Link>
 *      would throw outside a Router context and make the screens untestable
 *      without adding router plumbing to a component that needs none.
 *
 * NOT auto-navigation: staying put is the documented intent (see ResumePage's
 * header comment) so the student can read what was saved before moving on.
 * This gives them the exit, it does not take it for them.
 */
export function GoToDashboard() {
  return (
    <a className="btn btn-primary btn-full" href="/dashboard">
      Go to dashboard
    </a>
  );
}
