import type { ReviewCounters } from '../../lib/resumeApi.mjs';

export interface CommitBarProps {
  counters: ReviewCounters;
  confirming: boolean;
  justSaved: boolean;
  error: string | null;
  onConfirm(): void;
}

/**
 * Fixed bottom bar: what confirming will actually do, and the button that does it.
 *
 * The status line takes the SAME `counters` object the ledger renders, rather
 * than recomputing from sections/drafts. Two independent counts of the same
 * thing drift the moment one call site changes, and the failure mode here is a
 * bar that promises "3 fields will stay empty" above a ledger reading 4 --
 * which would make the student distrust both numbers.
 */
export function CommitBar({ counters, confirming, justSaved, error, onConfirm }: CommitBarProps) {
  const { gaps, total, edited } = counters;

  const status =
    gaps > 0
      ? `Confirming now saves ${String(total - gaps)} of ${String(total)} fields. ${String(gaps)} ${
          gaps === 1 ? 'field stays' : 'fields stay'
        } empty.`
      : `All ${String(total)} fields have a value${
          edited > 0 ? `, ${String(edited)} corrected by you` : ''
        }.`;

  return (
    <div className="rv-commit">
      <div className="rv-commit-inner">
        <p className="rv-commit-status">
          {error ? <span className="rv-commit-error" role="alert">{error}</span> : status}
        </p>
        <button
          type="button"
          className="rv-commit-button"
          onClick={onConfirm}
          disabled={confirming || justSaved}
        >
          {justSaved ? 'Saved ✓' : confirming ? 'Saving…' : 'Confirm all'}
        </button>
      </div>
    </div>
  );
}
