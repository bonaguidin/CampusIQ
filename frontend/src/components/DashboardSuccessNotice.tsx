import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { readSuccessNotice } from '../lib/successNotice.mjs';
import type { SuccessNotice } from '../lib/successNotice.mjs';

/**
 * The acknowledgement that replaced the resume and transcript "done" screens.
 *
 * WHY IT IS A DASHBOARD ELEMENT AND NOT A PAGE. Confirming a review has exactly
 * one sensible next destination, so asking the student to click "Go to
 * dashboard" was asking them to perform a decision that had already been made
 * for them. The confirmation now navigates, and the only thing the old screen
 * carried that the dashboard could not say for itself -- "that worked" -- comes
 * along as router state.
 *
 * WHY IT IS READ FROM location.state AND THEN ERASED. The notice is about one
 * transition, not about the dashboard, so it must not survive a reload or
 * reappear on the next visit. React Router keeps `state` on the history entry,
 * where a refresh WOULD restore it, so the first effect below replaces that
 * entry with a stateless one. After that the fact is held in component state
 * only: dismissing it, reloading, or navigating back all leave nothing behind.
 *
 * ACCESSIBILITY. The live region is always mounted and starts empty; the notice
 * text is inserted into it a tick later. A role="status" region that is created
 * with its text already in place is frequently not announced at all -- the
 * change is what assistive technology reports, so there has to be a change.
 * Nothing is focused: this is a confirmation of something already finished, and
 * moving focus would drop the student somewhere they did not ask to be.
 */
export function DashboardSuccessNotice() {
  const location = useLocation();
  const navigate = useNavigate();
  const [notice, setNotice] = useState<SuccessNotice | null>(null);

  useEffect(() => {
    const found = readSuccessNotice(location.state);
    if (!found) return;
    setNotice(found);
    // Same entry, no state: a refresh from here shows the dashboard alone.
    void navigate(`${location.pathname}${location.search}`, { replace: true, state: null });
    // Deliberately once, on mount, with an empty dependency list: the notice
    // belongs to the navigation that mounted this component, and re-running on
    // location changes would only ever re-read state this effect has cleared.
  }, []);

  return (
    <div className="dash-notice-region" role="status" aria-live="polite">
      {notice && (
        <div className="dash-notice" data-success-type={notice.type}>
          <span className="dash-notice-mark" aria-hidden="true">
            ✓
          </span>
          <p className="dash-notice-text">{notice.message}</p>
          <button
            type="button"
            className="dash-notice-dismiss"
            onClick={() => setNotice(null)}
            aria-label="Dismiss this message"
          >
            ×
          </button>
        </div>
      )}
    </div>
  );
}
