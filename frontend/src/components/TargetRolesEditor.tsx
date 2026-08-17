import { useState } from 'react';
import { useSupportedTargetRoles } from '../hooks/useSupportedTargetRoles';

interface TargetRolesEditorProps {
  roles: string[];
  isEditing: boolean;
  onChange(roles: string[]): void;
}

// Career analysis (FIT/GAP/SHIFT/Course Discovery) only has coverage for a
// curated role vocabulary (GradusIQ_career/data/role_requirements.json). A
// target role outside it doesn't fail loudly -- it silently produces an
// empty or under-grounded result that reads as "nothing relevant" instead
// of "GradusIQ doesn't have analysis coverage for this role yet". New roles
// are added only from the supported list (a plain <select>, not free text,
// per the small role count); existing unsupported values are never deleted
// or rewritten -- they stay visible with a clear coverage badge and can be
// removed like any other role.
function isSupported(role: string, supportedRoles: string[] | null): boolean | null {
  if (supportedRoles === null) return null; // still loading -- don't claim either way
  return supportedRoles.includes(role);
}

function CoverageBadge({ role, supportedRoles }: { role: string; supportedRoles: string[] | null }) {
  const supported = isSupported(role, supportedRoles);
  if (supported !== false) return null;
  return (
    <span className="course-discovery-status-badge course-discovery-status-badge--verify">
      Analysis coverage unavailable
    </span>
  );
}

export function TargetRolesEditor({ roles, isEditing, onChange }: TargetRolesEditorProps) {
  const supportedRoles = useSupportedTargetRoles();
  const [selectedToAdd, setSelectedToAdd] = useState('');

  if (!isEditing) {
    if (!roles || roles.length === 0) {
      return <p className="empty-state">No target roles added yet.</p>;
    }
    return (
      <div className="tag-chips-view">
        {roles.map((r) => (
          <span key={r} className="target-role-chip-group">
            <span className="tag-chip tag-chip-view">{r}</span>
            <CoverageBadge role={r} supportedRoles={supportedRoles} />
          </span>
        ))}
      </div>
    );
  }

  const addableRoles = (supportedRoles ?? []).filter((role) => !roles.includes(role));

  function addSelectedRole() {
    if (!selectedToAdd) return;
    onChange([...roles, selectedToAdd]);
    setSelectedToAdd('');
  }

  function removeRole(role: string) {
    onChange(roles.filter((r) => r !== role));
  }

  return (
    <div className="tag-input-field">
      <span className="form-label">Target Roles</span>

      {roles.length > 0 && (
        <div className="tag-input-container">
          {roles.map((role) => (
            <span key={role} className="target-role-chip-group">
              <span className="tag-chip">
                {role}
                <button
                  type="button"
                  className="tag-remove"
                  onClick={() => removeRole(role)}
                  aria-label={`Remove ${role}`}
                >
                  ×
                </button>
              </span>
              <CoverageBadge role={role} supportedRoles={supportedRoles} />
            </span>
          ))}
        </div>
      )}

      <div className="target-role-add-row">
        <label htmlFor="target-role-add-select" className="sr-only">
          Add a supported target role
        </label>
        <select
          id="target-role-add-select"
          className="form-select"
          value={selectedToAdd}
          onChange={(event) => setSelectedToAdd(event.target.value)}
          // Not disabled while supportedRoles is still loading (null): a
          // disabled control can never receive the auto-focus a freshly
          // opened field editor gives its first input/select/textarea (see
          // CareerProfile's FieldSlot -> revealField), which would leave
          // nothing in the field focused at all until the fetch resolves.
          disabled={supportedRoles !== null && addableRoles.length === 0}
        >
          <option value="">
            {supportedRoles === null ? 'Loading supported roles…' : 'Choose a supported role to add…'}
          </option>
          {addableRoles.map((role) => (
            <option key={role} value={role}>
              {role}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={addSelectedRole}
          disabled={!selectedToAdd}
        >
          Add role
        </button>
      </div>
      <p className="target-role-add-note">
        Career analysis only covers a curated set of roles today. Choose one from the list to add
        it -- existing roles outside this list stay on your profile and can still be removed.
      </p>
    </div>
  );
}
