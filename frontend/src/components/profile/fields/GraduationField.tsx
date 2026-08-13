import type { ProfileChanges } from '../../../api/profile';

/**
 * Expected graduation, as the season/year pair that produces it.
 *
 * EXTRACTED FROM ProfileCompletionForm, NOT REWRITTEN. The column stores one
 * string ("Spring 2028"); the student answers it with two selects. The pair
 * travels together for the same reason the major pair does -- half an answer
 * is not a smaller answer, it is an invalid one, and only the pair can tell
 * "not set" from "half set".
 */
export interface GraduationValue {
  season: string;
  year: string;
}

/** The shape the column is stored in, and the only shape read back out. */
const STORED = /^(Spring|Fall) (20\d{2})$/;

/** How many years forward the picker offers. */
const YEAR_SPAN = 12;

export function graduationValueFrom(stored: string | null | undefined): GraduationValue {
  const match = stored?.match(STORED);
  return { season: match?.[1] ?? '', year: match?.[2] ?? '' };
}

/** The stored string, or null for "not set". Never a half-filled string. */
export function graduationToStore(value: GraduationValue): string | null {
  return value.season && value.year ? `${value.season} ${value.year}` : null;
}

/**
 * The selectable years.
 *
 * A stored year outside the forward window is prepended rather than dropped:
 * the picker must be able to show back what the profile already holds, even
 * when that is a date in the past.
 */
export function graduationYears(current: string): string[] {
  const years = Array.from({ length: YEAR_SPAN }, (_, index) => String(new Date().getFullYear() + index));
  if (current && !years.includes(current)) years.unshift(current);
  return years;
}

/**
 * BOTH OR NEITHER. Either select alone is not a partial answer that can be
 * stored -- the column has nowhere to put a season without a year.
 */
export function validateGraduation(value: GraduationValue): string | null {
  const half = (value.season && !value.year) || (!value.season && value.year);
  return half ? 'Choose both a graduation season and year, or leave both blank.' : null;
}

/** The PATCH fragment, or {} when the stored value already says this. */
export function graduationChanges(
  value: GraduationValue,
  stored: string | null | undefined,
): ProfileChanges {
  const next = graduationToStore(value);
  return next === (stored ?? null) ? {} : { expected_graduation: next };
}

/** The controlled selects. Rendered identically by both hosts. */
export function GraduationInputs({
  value,
  onChange,
  disabled = false,
}: {
  value: GraduationValue;
  onChange(next: GraduationValue): void;
  disabled?: boolean;
}) {
  const years = graduationYears(value.year);

  return (
    <div className="profile-graduation">
      <label>
        Season
        <select
          value={value.season}
          disabled={disabled}
          onChange={(event) => { onChange({ ...value, season: event.target.value }); }}
        >
          <option value="">Not set</option>
          <option>Spring</option>
          <option>Fall</option>
        </select>
      </label>
      <label>
        Year
        <select
          value={value.year}
          disabled={disabled}
          onChange={(event) => { onChange({ ...value, year: event.target.value }); }}
        >
          <option value="">Not set</option>
          {years.map((year) => (
            <option key={year}>{year}</option>
          ))}
        </select>
      </label>
    </div>
  );
}
