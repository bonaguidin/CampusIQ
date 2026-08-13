import { useEffect, useState, type ReactNode } from 'react';
import { updateProfile, type ProfileChanges } from '../../../api/profile';
import { EditableSection } from '../../EditableSection';

/**
 * One independently-saved field, inline on the page it describes.
 *
 * WHY THE SAVE IS EXPLICIT AND NOT ON BLUR. Three of the four fields that use
 * this have a legal intermediate state that blur would either persist or
 * reject: season without a year, a switching student mid-way through typing a
 * major, and TagInput -- whose own onBlur already commits a pending tag, so a
 * second blur handler above it would race the commit it depends on. An Edit /
 * Save / Cancel shell is also what CareerPanel already does for the demo
 * profile, so this is the app's existing answer to per-section saving rather
 * than a new one.
 *
 * EditableSection is used unmodified. It takes `children: ReactNode` and
 * `errors: string[]`, which is all a two-input field needs -- the coupling
 * between the inputs lives in the field component, and the validation message
 * it produces is just another string in the list.
 *
 * ONE FIELD, ONE REQUEST, ONE RELOAD. Each save PATCHes only its own keys and
 * then reloads the profile, so N edited fields cost N reloads. That is the
 * accepted trade for fields that commit independently: the alternative is a
 * page-level dirty buffer, which is the batch form this surface replaces.
 */
export function InlineEditableField<T>({
  title,
  value,
  toChanges,
  validate,
  accessToken,
  onSaved,
  openNonce = null,
  editLabel = 'Edit',
  children,
}: {
  title: string;
  /** The canonical current value. Re-read on every edit, never cached across one. */
  value: T;
  toChanges(draft: T): ProfileChanges;
  validate?(draft: T): string | null;
  accessToken: string;
  onSaved(): Promise<void>;
  /**
   * Bumped when something off-page -- the checklist, or a skipped analysis --
   * sends the student here to answer this. Opening the editor is the whole
   * point of arriving: landing on a read-only row with an Edit button would
   * make the student ask for the same thing twice.
   */
  openNonce?: number | null;
  editLabel?: string;
  children(draft: T, setDraft: (next: T) => void, editing: boolean): ReactNode;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<T>(value);
  const [saving, setSaving] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);

  // Deliberately not folded into startEdit's callers: arriving by request is
  // not a click, and the two must not diverge if one ever grows a side effect.
  useEffect(() => {
    if (openNonce === null) return;
    setDraft(value);
    setErrors([]);
    setEditing(true);
    // `value` is read, not depended on: re-running when the profile reloads
    // after a save would reopen an editor the student had just closed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [openNonce]);

  function startEdit() {
    // Seeded here rather than held in sync: the canonical value changes under
    // this component whenever any field on the page saves, and a draft that
    // tracked it would discard what the student was part-way through typing.
    setDraft(value);
    setErrors([]);
    setEditing(true);
  }

  function cancel() {
    setDraft(value);
    setErrors([]);
    setEditing(false);
  }

  async function save() {
    const invalid = validate?.(draft) ?? null;
    if (invalid) {
      setErrors([invalid]);
      return;
    }
    const changes = toChanges(draft);
    // Nothing to say. Closing without a request is not a silent failure -- the
    // stored answer already reads the way the student just asked it to.
    if (Object.keys(changes).length === 0) {
      setErrors([]);
      setEditing(false);
      return;
    }
    setSaving(true);
    setErrors([]);
    try {
      await updateProfile(accessToken, changes);
      await onSaved();
      setEditing(false);
    } catch (error) {
      setErrors([error instanceof Error ? error.message : 'Your profile could not be saved.']);
    } finally {
      setSaving(false);
    }
  }

  return (
    <EditableSection
      title={title}
      isEditing={editing}
      onEdit={startEdit}
      onSave={() => { void save(); }}
      onCancel={cancel}
      saving={saving}
      errors={errors}
      editLabel={editLabel}
    >
      {children(editing ? draft : value, setDraft, editing)}
    </EditableSection>
  );
}
