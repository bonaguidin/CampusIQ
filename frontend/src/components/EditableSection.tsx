import type { ReactNode } from 'react';

interface EditableSectionProps {
  title: string;
  isEditing: boolean;
  onEdit(): void;
  onSave(): void;
  onCancel(): void;
  saving?: boolean;
  errors?: string[];
  children: ReactNode;
}

export function EditableSection({
  title,
  isEditing,
  onEdit,
  onSave,
  onCancel,
  saving = false,
  errors = [],
  children,
}: EditableSectionProps) {
  return (
    <div className="editable-section card">
      <div className="editable-section-header">
        <h3 className="editable-section-title">{title}</h3>
        <div className="editable-section-actions">
          {isEditing ? (
            <>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={onSave}
                disabled={saving}
                aria-busy={saving}
              >
                {saving ? 'Saving…' : 'Save'}
              </button>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={onCancel}
                disabled={saving}
              >
                Cancel
              </button>
            </>
          ) : (
            <button
              type="button"
              className="btn btn-ghost btn-sm"
              onClick={onEdit}
            >
              Edit
            </button>
          )}
        </div>
      </div>

      {errors.length > 0 && (
        <ul className="section-errors" role="alert" aria-label="Validation errors">
          {errors.map((err, idx) => (
            <li key={idx} className="section-error-item">
              {err}
            </li>
          ))}
        </ul>
      )}

      <div className="editable-section-body">{children}</div>
    </div>
  );
}
