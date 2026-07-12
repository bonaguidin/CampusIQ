import { TagInput } from './TagInput';

interface TargetRolesEditorProps {
  roles: string[];
  isEditing: boolean;
  onChange(roles: string[]): void;
}

export function TargetRolesEditor({ roles, isEditing, onChange }: TargetRolesEditorProps) {
  if (!isEditing) {
    if (!roles || roles.length === 0) {
      return <p className="empty-state">No target roles added yet.</p>;
    }
    return (
      <div className="tag-chips-view">
        {roles.map((r) => (
          <span key={r} className="tag-chip tag-chip-view">
            {r}
          </span>
        ))}
      </div>
    );
  }

  return (
    <TagInput
      label="Target Roles"
      value={roles}
      onChange={onChange}
      placeholder="Add a role and press Enter…"
    />
  );
}
