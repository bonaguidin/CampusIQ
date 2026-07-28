-- Adds per-institution brand colors so the frontend can theme the
-- rail/accent per school instead of the neutral default palette.
-- Not applied. DDL + seed UPDATEs only. Does not touch any frontend file.

-- ============================================================================
-- 1. Columns
-- ============================================================================

alter table institutions
  add column brand_primary_hex text null,
  add column brand_rail_hex text null,
  add column brand_on_primary_hex text null;

comment on column institutions.brand_primary_hex is
  'Institution brand accent color, e.g. "#500000". Null means no brand '
  'colors are set for this institution -- the app falls back to its '
  'neutral default palette.';

comment on column institutions.brand_rail_hex is
  'Institution brand color for the full-height dark rail surface. Null '
  'means no brand colors are set for this institution -- the app falls '
  'back to its neutral default palette.';

comment on column institutions.brand_on_primary_hex is
  'Text/icon color rendered on top of brand_primary_hex. Null means no '
  'brand colors are set for this institution -- the app falls back to '
  'its neutral default palette.';

alter table institutions
  add constraint institutions_brand_primary_hex_format
    check (brand_primary_hex is null or brand_primary_hex ~ '^#[0-9A-Fa-f]{6}$');

alter table institutions
  add constraint institutions_brand_rail_hex_format
    check (brand_rail_hex is null or brand_rail_hex ~ '^#[0-9A-Fa-f]{6}$');

alter table institutions
  add constraint institutions_brand_on_primary_hex_format
    check (brand_on_primary_hex is null or brand_on_primary_hex ~ '^#[0-9A-Fa-f]{6}$');

-- ============================================================================
-- 2. Seed: Texas A&M University
-- ============================================================================

-- Aggie Maroon -- this is the app's prior default accent/rail before the
-- neutral "warm technical slate" recolor, now scoped to TAMU specifically
-- rather than being the app-wide default.
update institutions
set
  brand_primary_hex = '#500000',
  brand_rail_hex = '#2B0B0B',
  brand_on_primary_hex = '#FFFFFF'
where name = 'Texas A&M University';

-- ============================================================================
-- 3. Seed: Southern Methodist University
-- ============================================================================

-- SMU brand guidelines list blue (PMS 286, #0033A0) as the preferred
-- primary, with red (#C8102E) as an alternate. Red is deliberately NOT
-- seeded here -- one primary per institution.
-- brand_rail_hex (#171E2B) is not an official SMU brand swatch: it's a
-- dark, desaturated navy derived from SMU Blue's hue (~221deg), lowered
-- in saturation and lightness to work as a full-height rail behind light
-- text. White (#FFFFFF) on #171E2B measures 16.71:1, comfortably past
-- the 7:1 (AAA) requirement for this rail.
update institutions
set
  brand_primary_hex = '#0033A0',
  brand_rail_hex = '#171E2B',
  brand_on_primary_hex = '#FFFFFF'
where name = 'Southern Methodist University';
