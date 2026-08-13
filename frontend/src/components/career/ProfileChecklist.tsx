import type { ChecklistField } from '../../lib/profileChecklist';

/**
 * What the analyses are still waiting for, docked where the student is.
 *
 * WHAT THIS REPLACED AND WHY. A modal, opened from a skipped analysis, was the
 * only way to answer these. It covered the page that stated the gap, and it
 * only ever appeared *after* a student ran an analysis and was told no -- so
 * the profile could sit incomplete indefinitely as long as nobody pressed the
 * button. This says the same thing without being asked, and stays out of the
 * way while saying it.
 *
 * STICKY, NOT FIXED, AND NOT AN OVERLAY. It scrolls with .stage-main and
 * settles at the top of it. Nothing is covered, nothing steals focus, and the
 * page underneath stays fully usable -- which is the whole difference between
 * this and the dialog it replaces.
 *
 * MODELLED ON THE RESUME REVIEW'S LEDGER BAR, deliberately not imported from
 * it: LedgerBar counts fields on a form it shares state with and is typed to
 * that screen's ReviewCounters. The shape is right and the coupling is not, so
 * this is the same idea built from this surface's own data.
 *
 * COUNTS ONLY WHAT GATES SOMETHING. Four fields, not the six the Career tab
 * can edit -- see CHECKLIST_FIELDS. A count that included AI comfort would be
 * telling students they are incomplete over a field no analysis reads.
 */
export function ProfileChecklist({
  missing,
  onJump,
}: {
  missing: ChecklistField[];
  onJump(field: ChecklistField, trigger: HTMLElement): void;
}) {
  const complete = missing.length === 0;

  return (
    <section
      className={`pc-dock${complete ? ' pc-dock--complete' : ''}`}
      aria-label="Profile details needed"
      data-profile-checklist=""
    >
      <div className="pc-dock-lead">
        <span className="pc-dock-count">{complete ? '✓' : missing.length}</span>
        <span className="pc-dock-label">
          {complete
            ? 'All details provided'
            : `${missing.length === 1 ? 'detail' : 'details'} needed for your analyses`}
        </span>
      </div>

      {/* The list is the whole control: each gap is the button that goes and
          fixes it. There is no separate "open" action, because there is no
          longer anything to open. */}
      {!complete && (
        <ul className="pc-dock-items">
          {missing.map((field) => (
            <li key={field.path}>
              <button
                type="button"
                className="pc-dock-item"
                // The dotted path is the address, never the label: base.py
                // authors the words a student reads, and a raw path on screen
                // is a bug they are looking at.
                onClick={(event) => { onJump(field, event.currentTarget); }}
              >
                {field.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
