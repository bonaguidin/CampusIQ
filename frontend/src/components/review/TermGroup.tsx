import type { ReactNode } from 'react';

export interface TermGroupProps {
  /** Human label for the term, already resolved from the terms[] lookup. */
  label: string;
  /** Courses in this group. */
  count: number;
  /** Credits attempted in this group, pre-summed. */
  credits: string;
  children: ReactNode;
}

/**
 * One academic term's heading, wrapping the cards belonging to it.
 *
 * WHY THIS EXISTS AT ALL: the resume review has exactly two levels -- section
 * and card -- because a resume's entries have no meaningful order beyond the
 * section they sit in. Courses do: they belong to terms, and a transcript read
 * out of term order is not a transcript. This is the missing middle level, and
 * it is the only structural addition the transcript surface needs.
 *
 * It renders the rv-* section-head treatment (mono label, count, hairline)
 * rather than TranscriptReview's former transcript-* header, so a term heading
 * and a resume section heading are visibly the same kind of thing.
 */
export function TermGroup({ label, count, credits, children }: TermGroupProps) {
  return (
    <section className="rv-section rv-term">
      <h2 className="rv-section-head">
        {label}
        <span className="rv-section-count">{count}</span>
      </h2>
      <p className="rv-term-meta">
        {credits} credits attempted
      </p>
      {children}
    </section>
  );
}
