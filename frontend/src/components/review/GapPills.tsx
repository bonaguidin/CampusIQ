import type { ReviewField } from '../../lib/resumeApi.mjs';

export interface GapPillsProps {
  fields: readonly ReviewField[];
  idPrefix: string;
  onPromote(fieldName: string): void;
}

/**
 * The single row at the bottom of an entry card collecting every field the
 * resume did not supply.
 *
 * WHY ONE ROW RATHER THAN AN EMPTY ROW PER FIELD: an entry with three filled
 * fields and five empty ones reads, in the per-row form, as mostly absence --
 * the eye counts eight rows and finds five of them blank. Collapsing the empties
 * into one line keeps the card's height proportional to what was actually read,
 * and turns each gap into an invitation ("+ issuer") instead of a void.
 *
 * Each pill is a real <button>: clicking or pressing Enter/Space promotes it to
 * a full field row, already in edit mode.
 */
export function GapPills({ fields, idPrefix, onPromote }: GapPillsProps) {
  if (fields.length === 0) return null;

  return (
    <div className="rv-gaps">
      <span className="rv-gaps-label">not found</span>
      <span className="rv-gaps-list">
        {fields.map((field) => (
          <button
            key={field.name}
            type="button"
            className="rv-gap-pill"
            data-gap-pill={`${idPrefix}:${field.name}`}
            onClick={() => onPromote(field.name)}
          >
            + {field.label.toLowerCase()}
          </button>
        ))}
      </span>
    </div>
  );
}
