import type { TranscriptCrossCheck } from '../../lib/transcriptApi.mjs';

export interface CrossCheckNoticeProps {
  crossCheck: TranscriptCrossCheck;
}

const FIELD_LABELS: Record<string, string> = {
  gpa: 'GPA',
  term_gpa: 'term GPA',
  credit_hours: 'credit hours',
  attempted_hours: 'attempted hours',
  earned_hours: 'earned hours',
};

/**
 * Printed term totals against totals computed from the parsed rows.
 *
 * ADVISORY, NEVER BLOCKING. crosscheck.py calls this "surfaced, never
 * blocking", and the flow honours that: a mismatch renders as something to
 * look at, the review continues normally, and confirmation stays available. A
 * disagreement usually means one course was misread -- which is precisely what
 * the student is here to correct -- so blocking on it would prevent the fix.
 *
 * Renders nothing when the totals agree. A "no problems found" banner on every
 * upload trains people to ignore the space where the real warning appears.
 */
export function CrossCheckNotice({ crossCheck }: CrossCheckNoticeProps) {
  if (crossCheck.ok || crossCheck.mismatches.length === 0) return null;

  return (
    <section className="rv-crosscheck" role="note" aria-labelledby="rv-crosscheck-head">
      <h2 className="rv-crosscheck-head" id="rv-crosscheck-head">
        Totals on the page don&rsquo;t match the courses we read
      </h2>
      <p className="rv-crosscheck-lede">
        Your transcript prints a total that differs from adding up the courses below. Usually one
        course was misread — correcting it here fixes the difference. You can still confirm.
      </p>
      <ul className="rv-crosscheck-list">
        {crossCheck.mismatches.map((mismatch, index) => (
          <li className="rv-crosscheck-row" key={`${mismatch.term_label}-${mismatch.field}-${String(index)}`}>
            <span className="rv-crosscheck-term">{mismatch.term_label}</span>
            <span className="rv-crosscheck-field">
              {FIELD_LABELS[mismatch.field] ?? mismatch.field}
            </span>
            <span className="rv-crosscheck-values">
              printed <strong>{format(mismatch.printed)}</strong> · we read{' '}
              <strong>{format(mismatch.computed)}</strong>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function format(value: number | null): string {
  return value === null || value === undefined ? '—' : String(value);
}
