import type { ProfileChanges } from '../../../api/profile';

/**
 * The four answers, and the only place they are enumerated.
 *
 * EXTRACTED FROM ProfileCompletionForm, NOT REWRITTEN. Both the picker and the
 * read-only label map derive from this list, so a fifth option cannot be added
 * to one and missed by the other -- the Career tab previously carried its own
 * copy of the labels.
 */
export const AI_OPTIONS = [
  ['low', 'Low'],
  ['moderate', 'Moderate'],
  ['high', 'High'],
  ['not_sure', 'Not sure'],
] as const;

export type AiComfort = (typeof AI_OPTIONS)[number][0];

/** How a stored token reads on screen. Derived, never hand-maintained. */
export const AI_COMFORT_LABELS: Record<string, string> = Object.fromEntries(AI_OPTIONS);

/**
 * The label for a stored value.
 *
 * An unrecognised token passes through untouched rather than being swallowed,
 * the same way certificationEntries handles an unexpected status. Null is the
 * caller's to describe -- it means never asked, which is not an option here.
 */
export function aiComfortLabel(value: string | null | undefined): string | null {
  if (!value) return null;
  return AI_COMFORT_LABELS[value] ?? value;
}

/** The PATCH fragment. '' is written as null -- "never asked", not an answer. */
export function aiComfortChanges(next: string, stored: string | null | undefined): ProfileChanges {
  if (next === (stored ?? '')) return {};
  return { ai_anxiety_level: next ? (next as NonNullable<ProfileChanges['ai_anxiety_level']>) : null };
}

/**
 * The controlled radio group.
 *
 * NO OPTION STANDS FOR "UNANSWERED". Null means never asked, which is a
 * different state from 'not_sure' (asked, does not know) -- see the
 * 20260812143000 migration. An unselected group is how null looks, so there is
 * deliberately no checked-by-default option to represent it.
 *
 * `name` is a prop because two hosts can render this on one page, and radios
 * sharing a name would form a single group across both.
 */
export function AiComfortOptions({
  value,
  onChange,
  disabled = false,
  name = 'ai-comfort',
}: {
  value: string;
  onChange(next: AiComfort): void;
  disabled?: boolean;
  name?: string;
}) {
  return (
    <fieldset className="profile-ai-group">
      <legend>How comfortable are you working with AI?</legend>
      <div className="profile-ai-options">
        {AI_OPTIONS.map(([option, label]) => (
          <label key={option}>
            <input
              type="radio"
              name={name}
              value={option}
              checked={value === option}
              disabled={disabled}
              onChange={() => { onChange(option); }}
            />
            {label}
          </label>
        ))}
      </div>
      <small>Skip this if you'd rather not say.</small>
    </fieldset>
  );
}

/**
 * The inline input for this field. Saving belongs to InlineEditableField so a
 * radio choice remains a draft until the student explicitly commits it, just
 * like every other Career Profile field.
 */
export function AiComfortField({
  value,
  onChange,
  name,
}: {
  value: string;
  onChange(next: AiComfort): void;
  name?: string;
}) {
  return (
    <div className="cp-field-edit">
      <AiComfortOptions
        value={value}
        onChange={onChange}
        name={name}
      />
    </div>
  );
}
