import { NO_INTENDED_MAJOR, isNoIntendedMajor } from '../../../lib/majorSentinel';
import type { ProfileChanges } from '../../../api/profile';

/**
 * The intended-major answer, as the two coupled inputs that produce it.
 *
 * EXTRACTED FROM ProfileCompletionForm, NOT REWRITTEN. The checkbox gates the
 * text field, and "not switching" is a positive write of the sentinel rather
 * than an erasure -- the API rejects a blank string with a 422 and treats an
 * omitted key as "leave untouched", so there is no way to say "staying" except
 * by writing it. That reasoning lives in majorSentinel.ts, which this file does
 * not touch; what moved here is only the pair of inputs and the three rules
 * that bind them.
 *
 * The pair travels together because neither half is answerable alone: the text
 * field's validity is decided by the checkbox, so a save that saw only one of
 * them could not tell a switching student who has not named a major from a
 * student who is staying.
 */
export interface MajorValue {
  switching: boolean;
  /** The typed major. Always '' when not switching -- never the sentinel. */
  majorIntended: string;
}

/**
 * Read the stored column into the pair.
 *
 * The sentinel is a stored answer ("staying"), never something the student
 * typed, so it drives the checkbox and leaves the text field empty rather than
 * showing "N/A" back as if it were a major they entered.
 */
export function majorValueFrom(storedIntended: string | null | undefined): MajorValue {
  const switching = !isNoIntendedMajor(storedIntended);
  return { switching, majorIntended: switching ? (storedIntended ?? '') : '' };
}

/** What the save writes: the typed major when switching, the sentinel when not. */
export function intendedToSave(value: MajorValue): string {
  return value.switching ? value.majorIntended.trim() : NO_INTENDED_MAJOR;
}

/**
 * The one rule this field owns.
 *
 * Only a *switching* student owes an intended major. Not switching is a
 * complete answer, so it satisfies the requirement rather than failing it.
 */
export function validateMajor(value: MajorValue): string | null {
  if (value.switching && !value.majorIntended.trim()) {
    return 'Name the major you are switching to, or untick the box.';
  }
  return null;
}

/** The PATCH fragment, or {} when the stored answer already says this. */
export function majorChanges(value: MajorValue, storedIntended: string | null | undefined): ProfileChanges {
  const next = intendedToSave(value);
  return next === (storedIntended ?? '') ? {} : { major_intended: next };
}

/**
 * The major the student is enrolled in now.
 *
 * A SEPARATE UNIT FROM THE PAIR ABOVE, and deliberately a much simpler one: it
 * is plain text with no sentinel, no gate and nothing to validate. There is no
 * N/A convention here -- "no current major" is an empty column, not a stored
 * answer, because unlike "am I switching" it is not a question the student has
 * to have answered.
 *
 * It is split out inline because the two halves change for unrelated reasons:
 * correcting a mis-parsed current major and deciding to switch are different
 * events, and pairing them made the first one wait on the second.
 */
export function majorCurrentChanges(value: string, stored: string | null | undefined): ProfileChanges {
  const next = value.trim();
  return next === (stored ?? '').trim() ? {} : { major_current: next };
}

/** The controlled input. No rules to enforce, so no validate() beside it. */
export function CurrentMajorInput({
  value,
  onChange,
  disabled = false,
}: {
  value: string;
  onChange(next: string): void;
  disabled?: boolean;
}) {
  return (
    <label className="profile-form-field">
      {/* Wrapped so the inline host can hide it: there, EditableSection's title
          already reads "Current major" two lines above. The wrapper carries no
          styling of its own, so the completion form is unchanged. */}
      <span className="field-label-text">Current major</span>
      <input
        value={value}
        disabled={disabled}
        placeholder="e.g. Computer Science"
        onChange={(event) => { onChange(event.target.value); }}
      />
    </label>
  );
}

/**
 * The controlled inputs, with no opinion about where they sit.
 *
 * Both hosts render this: the inline Details row wraps it in an editable
 * section that saves on its own, and the completion form renders it inside its
 * batch submit. Neither owns the coupling, so the two cannot drift.
 */
export function MajorInputs({
  value,
  onChange,
  helper,
  disabled = false,
  idPrefix = 'major',
}: {
  value: MajorValue;
  onChange(next: MajorValue): void;
  /** Overrides the default hint -- the form uses it to show why FIT wants this. */
  helper?: string | null;
  disabled?: boolean;
  idPrefix?: string;
}) {
  const { switching, majorIntended } = value;
  const helpId = `${idPrefix}-intended-help`;

  return (
    <>
      {/* The switch decides whether the field below is answerable at all, so
          it sits above it and gates it, rather than asking the student to
          encode the same answer by typing a sentinel into the field. */}
      <label className="profile-form-check">
        <input
          type="checkbox"
          checked={switching}
          disabled={disabled}
          onChange={(event) =>
            onChange(
              event.target.checked
                ? { switching: true, majorIntended }
                : { switching: false, majorIntended: '' },
            )
          }
        />
        I'm planning to switch majors
      </label>
      <label className="profile-form-field profile-form-field--gated">
        <span className="field-label-text">Intended major</span>
        <input
          value={majorIntended}
          onChange={(event) => { onChange({ switching, majorIntended: event.target.value }); }}
          disabled={!switching || disabled}
          placeholder={switching ? 'e.g. Computer Science' : ''}
          aria-describedby={helpId}
        />
        <small id={helpId}>
          {helper ??
            (switching
              ? 'The major you are switching to.'
              : 'Not switching — we will record this as N/A.')}
        </small>
      </label>
    </>
  );
}
