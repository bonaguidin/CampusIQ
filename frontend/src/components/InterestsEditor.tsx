import { TagInput } from './TagInput';

interface InterestsEditorProps {
  interests: string[];
  isEditing: boolean;
  onChange(interests: string[]): void;
}

export function InterestsEditor({ interests, isEditing, onChange }: InterestsEditorProps) {
  if (!isEditing) {
    if (!interests || interests.length === 0) {
      return <p className="empty-state">No interests added yet.</p>;
    }
    return (
      <div className="tag-chips-view">
        {interests.map((i) => (
          <span key={i} className="tag-chip tag-chip-view">
            {i}
          </span>
        ))}
      </div>
    );
  }

  return (
    <TagInput
      label="Interests"
      value={interests}
      onChange={onChange}
      placeholder="Add an interest and press Enter…"
    />
  );
}
