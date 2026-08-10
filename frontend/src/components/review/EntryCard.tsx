import { useState } from 'react';
import { REVIEW_SECTIONS, fieldGlyph, isEmptyValue } from '../../lib/resumeApi.mjs';
import type { ReviewField, ReviewRow, SectionKey } from '../../lib/resumeApi.mjs';
import { FieldRow } from './FieldRow';
import { GapPills } from './GapPills';

export interface EntryCardProps {
  table: SectionKey;
  original: ReviewRow;
  draft: ReviewRow;
  index: number;
  locked: boolean;
  message: string | null;
  tone: 'error' | 'saved';
  onChange(fieldName: string, next: unknown): void;
  /** Resolves to whether a save round-tripped; gates FieldRow's confirmation flash. */
  onCommit(overrides?: Record<string, unknown>): Promise<boolean> | boolean;
}

/**
 * The card's serif headline: the section's title field, else a fallback.
 *
 * A section with NO titleField (career_profile, which is a singleton) gets the
 * section's own label rather than "career profile 1" -- numbering an entry that
 * can only ever be one of a kind reads like a bug. A section that HAS a
 * titleField but a blank value still numbers, because there really are others
 * to tell it apart from.
 */
function titleFor(table: SectionKey, row: ReviewRow, index: number): string {
  const section = REVIEW_SECTIONS[table];
  const field = section.titleField;
  if (!field) return section.label;
  const value = row[field];
  if (typeof value === 'string' && value.trim()) return value.trim();
  return `${section.singular} ${String(index + 1)}`;
}

/**
 * The muted mono line under the title: up to two secondary values, whichever
 * of the section's non-title fields are filled, joined with a middot. Purely
 * derived -- no per-section subtitle config to drift out of sync with the
 * fields actually present.
 */
function subtitleFor(table: SectionKey, row: ReviewRow): string {
  const section = REVIEW_SECTIONS[table];
  const parts: string[] = [];
  for (const field of section.fields) {
    if (field.name === section.titleField) continue;
    if (field.type === 'textarea' || field.type === 'list') continue;
    const value = row[field.name];
    if (typeof value === 'string' && value.trim()) {
      parts.push(value === 'in_progress' ? 'in progress' : value.trim());
    } else if (typeof value === 'number') {
      parts.push(String(value));
    }
    if (parts.length === 2) break;
  }
  return parts.join(' · ');
}

export function EntryCard({
  table,
  original,
  draft,
  index,
  locked,
  message,
  tone,
  onChange,
  onCommit,
}: EntryCardProps) {
  // Fields promoted from a gap pill this session. They render as real rows even
  // while still empty, so the student can type into what they just clicked --
  // without this, an empty field would immediately collapse back into a pill.
  const [promoted, setPromoted] = useState<string[]>([]);
  const section = REVIEW_SECTIONS[table];
  const idPrefix = `${table}:${original.id}`;

  const shown: ReviewField[] = [];
  const gaps: ReviewField[] = [];
  for (const field of section.fields) {
    const filled = !isEmptyValue(draft[field.name]);
    if (filled || promoted.includes(field.name)) shown.push(field);
    else gaps.push(field);
  }

  return (
    <article className="rv-card">
      <header className="rv-card-head">
        <h3 className="rv-card-title">{titleFor(table, draft, index)}</h3>
        {subtitleFor(table, draft) && (
          <p className="rv-card-sub">{subtitleFor(table, draft)}</p>
        )}
        {locked && <span className="rv-card-locked">confirmed · read only</span>}
      </header>

      <div className="rv-card-fields">
        {shown.map((field) => (
          <FieldRow
            key={field.name}
            field={field}
            idPrefix={idPrefix}
            glyph={fieldGlyph(original, draft, field.name)}
            value={draft[field.name]}
            locked={locked}
            autoEdit={promoted.includes(field.name) && isEmptyValue(draft[field.name])}
            onChange={(next) => onChange(field.name, next)}
            onCommit={onCommit}
          />
        ))}
      </div>

      {!locked && (
        <GapPills
          fields={gaps}
          idPrefix={idPrefix}
          onPromote={(name) => setPromoted((prev) => (prev.includes(name) ? prev : [...prev, name]))}
        />
      )}

      {message && (
        <p
          className={tone === 'error' ? 'rv-card-error' : 'rv-card-saved'}
          role={tone === 'error' ? 'alert' : 'status'}
        >
          {message}
        </p>
      )}
    </article>
  );
}
