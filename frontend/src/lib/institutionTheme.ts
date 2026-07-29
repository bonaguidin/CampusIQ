import { supabase } from './supabase';

// Applies/clears an institution's brand colors as inline custom
// properties on document.documentElement. Every alpha variant in
// index.css already derives from the *-rgb triplets (e.g. --rail-line
// is rgb(var(--rail-text-rgb) / 0.12)), so overriding one triplet here
// recolors all of its derived tokens for free.
//
// .login-* rules never reference these themeable properties -- they
// use the separate --neutral-* tokens (fixed literal values, see
// index.css), so the login page is unaffected regardless of what is
// set here.

export interface InstitutionTheme {
  brand_primary_hex: string | null;
  brand_rail_hex: string | null;
  brand_on_primary_hex: string | null;
}

const HEX_PATTERN = /^#[0-9A-Fa-f]{6}$/;

// Fixed lighten-toward-white amount for the hover state, applied to
// brand_primary_hex. Chosen so both a TAMU-maroon and an SMU-blue
// hover clear 4.5:1 against white --on-accent with comfortable margin
// (10.9:1 and 7.3:1 respectively) while still reading as a visibly
// lighter step up from the rest color.
const ACCENT_HOVER_LIGHTEN = 0.15;

function hexToChannels(hex: string): [number, number, number] {
  return [
    parseInt(hex.slice(1, 3), 16),
    parseInt(hex.slice(3, 5), 16),
    parseInt(hex.slice(5, 7), 16),
  ];
}

function hexToRgbTriplet(hex: string): string {
  return hexToChannels(hex).join(' ');
}

function lightenHexTowardWhite(hex: string, amount: number): string {
  const mix = (c: number) => Math.round(c + (255 - c) * amount);
  return hexToChannels(hex).map(mix).join(' ');
}

// Which inline custom properties a given brand_*_hex field controls.
const PROPERTY_MAP: Array<{ field: keyof InstitutionTheme; properties: string[] }> = [
  { field: 'brand_primary_hex', properties: ['--accent-rgb', '--institution-accent-rgb'] },
  { field: 'brand_rail_hex', properties: ['--rail-bg-rgb'] },
  { field: 'brand_on_primary_hex', properties: ['--on-accent-rgb'] },
];

// --accent-hover-rgb is derived (lightened) from brand_primary_hex
// rather than a 1:1 hex passthrough, so it isn't in PROPERTY_MAP, but
// it must still be cleared alongside everything else.
const ACCENT_HOVER_PROPERTY = '--accent-hover-rgb';

function applyOne(style: CSSStyleDeclaration, property: string, hex: string | null): void {
  if (hex === null) {
    // Explicit null: remove the override so :root's default applies.
    style.removeProperty(property);
    return;
  }
  if (!HEX_PATTERN.test(hex)) {
    console.warn(`institutionTheme: invalid hex ${JSON.stringify(hex)} for ${property}; skipping`);
    return;
  }
  style.setProperty(property, hexToRgbTriplet(hex));
}

export function applyInstitutionTheme(theme: InstitutionTheme | null): void {
  if (!theme) {
    clearInstitutionTheme();
    return;
  }
  const style = document.documentElement.style;
  for (const { field, properties } of PROPERTY_MAP) {
    const hex = theme[field];
    for (const property of properties) {
      applyOne(style, property, hex);
    }
  }

  const primary = theme.brand_primary_hex;
  if (primary === null) {
    style.removeProperty(ACCENT_HOVER_PROPERTY);
  } else if (!HEX_PATTERN.test(primary)) {
    console.warn(
      `institutionTheme: invalid hex ${JSON.stringify(primary)} for ${ACCENT_HOVER_PROPERTY}; skipping`,
    );
  } else {
    style.setProperty(ACCENT_HOVER_PROPERTY, lightenHexTowardWhite(primary, ACCENT_HOVER_LIGHTEN));
  }
}

export function clearInstitutionTheme(): void {
  const style = document.documentElement.style;
  for (const { properties } of PROPERTY_MAP) {
    for (const property of properties) {
      style.removeProperty(property);
    }
  }
  style.removeProperty(ACCENT_HOVER_PROPERTY);
}

// TEMPORARY: matches on the student's free-text institution name.
// After the adapter swap (dataAdapter.ts -> Supabase reads), this
// becomes a foreign-key lookup on the student's institution_id
// instead -- matching a school by free-text name is a stopgap for the
// demo JSON path only, not the intended long-term join.
export async function fetchInstitutionThemeByName(name: string): Promise<InstitutionTheme | null> {
  try {
    const { data, error } = await supabase
      .from('institutions')
      .select('brand_primary_hex, brand_rail_hex, brand_on_primary_hex')
      .eq('name', name)
      .maybeSingle();

    if (error || !data) {
      return null;
    }
    return data as InstitutionTheme;
  } catch {
    return null;
  }
}
