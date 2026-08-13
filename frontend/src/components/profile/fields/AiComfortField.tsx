import { useState } from 'react';
import { updateProfile, type ProfileChanges } from '../../../api/profile';

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
 * The self-saving inline form of the field.
 *
 * NO EDIT/SAVE/CANCEL SHELL, DELIBERATELY. The other four units have an
 * invalid intermediate state to protect -- a season without a year, a
 * switching student with no major named -- so they need a moment between
 * "changed" and "committed". Picking one of four radios has no such state:
 * every value the control can hold is a complete, valid answer, so a Save
 * button beside it would be a step that can only ever succeed.
 *
 * Re-picking the value already stored writes nothing rather than spending a
 * request to say what the server said.
 */
export function AiComfortField({
  value,
  accessToken,
  onSaved,
  name,
}: {
  value: string | null;
  accessToken: string;
  onSaved(): Promise<void>;
  name?: string;
}) {
  const [saving, setSaving] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  async function pick(next: AiComfort) {
    const changes = aiComfortChanges(next, value);
    if (Object.keys(changes).length === 0) return;
    setSaving(true);
    setFailure(null);
    try {
      await updateProfile(accessToken, changes);
      await onSaved();
    } catch (error) {
      setFailure(error instanceof Error ? error.message : 'Your profile could not be saved.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="cp-field-edit">
      <AiComfortOptions
        value={value ?? ''}
        onChange={(next) => { void pick(next); }}
        disabled={saving}
        name={name}
      />
      {saving && <p className="cp-field-status" role="status">Saving…</p>}
      {failure && <p className="profile-form-error" role="alert">{failure}</p>}
    </div>
  );
}
