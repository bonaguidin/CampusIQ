import type { TranscriptRecord, TranscriptTerm } from '../../lib/transcriptApi.mjs';

export interface RepeatExclusionsProps {
  rows: TranscriptRecord[];
  terms: Map<string, TranscriptTerm>;
}

/**
 * Confirmed attempts an institution's repeat policy dropped from the GPA.
 *
 * WHY THIS IS A SEPARATE SECTION AND NOT A FLAG ON THE COURSE LIST: repeat
 * exclusions live exclusively on CONFIRMED rows -- reconcile_repeats runs
 * inside the confirm flow -- while the list above is everything still
 * unconfirmed. The two sets are essentially disjoint, so a flag on the main
 * list would render for nobody. These are courses the student already
 * confirmed, shown again because their GPA treatment changed.
 *
 * WHY "STILL COUNTS TOWARD EARNED HOURS" IS THE LOUDEST LINE HERE: review.py
 * calls it "the counter-intuitive half of the rule and the first thing a
 * student will dispute". A student who reads only "excluded from GPA" will
 * conclude the course vanished from their degree progress, which is wrong. It
 * gets its own emphasized line rather than a parenthetical.
 */
export function RepeatExclusions({ rows, terms }: RepeatExclusionsProps) {
  if (rows.length === 0) return null;

  return (
    <section className="rv-section rv-repeats" aria-labelledby="rv-repeats-head">
      <h2 className="rv-section-head" id="rv-repeats-head">
        Excluded by repeat policy
        <span className="rv-section-count">{rows.length}</span>
      </h2>

      <p className="rv-repeats-lede">
        A later attempt replaced these in your GPA.{' '}
        <strong className="rv-repeats-emphasis">
          They still count toward your earned hours.
        </strong>
      </p>

      <ul className="rv-repeats-list">
        {rows.map((row) => (
          <li className="rv-repeat" key={row.id}>
            <span className="rv-repeat-code">{row.course_code}</span>
            <span className="rv-repeat-grade">{row.letter_grade ?? '—'}</span>
            <span className="rv-repeat-note">{describe(row, terms)}</span>
          </li>
        ))}
      </ul>

      <p className="rv-repeats-foot">
        To change this, correct the grade on the attempt above — the exclusion is recalculated
        each time you confirm.
      </p>
    </section>
  );
}

/**
 * How this row was superseded.
 *
 * `superseded_by` is null whenever the superseding row is not among the
 * caller's returned rows, and review.py still sends superseded_by_id for
 * exactly that case -- so the fallback names what it can rather than rendering
 * a broken reference or crashing on a missing object.
 */
function describe(row: TranscriptRecord, terms: Map<string, TranscriptTerm>): string {
  const exclusion = row.repeat_exclusion;
  if (!exclusion) return `${row.course_code} was replaced by a later attempt.`;

  const target = exclusion.superseded_by;
  // superseded_by is null when the superseding row is not among the caller's
  // rows. review.py still sends superseded_by_id for that case, so name what we
  // can rather than rendering a bare uuid or an empty reference.
  if (!target) return `${row.course_code} was replaced by a later attempt on your record.`;

  const term = target.term_id ? terms.get(target.term_id)?.label : null;
  const grade = target.letter_grade ? ` (${target.letter_grade})` : '';
  return term
    ? `${row.course_code} was replaced by ${target.course_code}${grade} from ${term}.`
    : `${row.course_code} was replaced by ${target.course_code}${grade}.`;
}
