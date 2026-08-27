import type { CatalogSearchResult, GradingSchema, PlanningTerm } from '../lib/termPlanning.mjs';

/**
 * Local-only stand-ins for what GPA Calculator (TermPlanner) normally reads
 * from GET /me/terms, /me/grading-schema, and /me/catalog/search -- all
 * session-scoped-only routes with no demo counterpart. These are computed/
 * curated client-side so the demo dashboard never issues a network call for
 * GPA Calculator at all, matching the "changes are local, never permanent"
 * philosophy for reads as well as writes.
 *
 * Term dates are computed RELATIVE TO `today`, not hardcoded -- the same
 * fix applied this session to GradusIQ_career/demo/local_requirement_tree.py
 * and to two CI tests that broke when real time crossed a hardcoded
 * 2026-08-24. A calendar built from absolute dates always eventually rots;
 * one built relative to "now" never does.
 */

const LONG_TERM_SPAN_YEARS = 4;

function isoDate(year: number, month: number, day: number): string {
  return new Date(Date.UTC(year, month - 1, day)).toISOString().slice(0, 10);
}

/**
 * A handful of Fall/Spring terms spanning from one year before `today` to
 * LONG_TERM_SPAN_YEARS after it -- enough for the dropdown to always have a
 * plausible "upcoming" term (the earliest start_date strictly after today,
 * same rule build_terms_view.py uses) regardless of when this actually runs.
 */
export function buildDemoTerms(today: Date): PlanningTerm[] {
  const terms: PlanningTerm[] = [];
  const startYear = today.getUTCFullYear() - 1;
  for (let year = startYear; year <= startYear + LONG_TERM_SPAN_YEARS; year += 1) {
    terms.push({
      key: `${year}-Spring`,
      id: null,
      label: `Spring ${year}`,
      year,
      season: 'Spring',
      sequence: null,
      start_date: isoDate(year, 1, 15),
      end_date: isoDate(year, 5, 10),
      enrolled: false,
      is_upcoming: false,
    });
    terms.push({
      key: `${year}-Fall`,
      id: null,
      label: `Fall ${year}`,
      year,
      season: 'Fall',
      sequence: null,
      start_date: isoDate(year, 8, 25),
      end_date: isoDate(year, 12, 12),
      enrolled: false,
      is_upcoming: false,
    });
  }
  // is_upcoming: the earliest start_date strictly after today -- mirrors
  // planning/term_view.py's build_terms_view exactly.
  let upcomingIndex = -1;
  let upcomingStart: Date | null = null;
  terms.forEach((term, index) => {
    if (!term.start_date) return;
    const start = new Date(`${term.start_date}T00:00:00Z`);
    if (start <= today) return;
    if (upcomingStart === null || start < upcomingStart) {
      upcomingStart = start;
      upcomingIndex = index;
    }
  });
  if (upcomingIndex >= 0) terms[upcomingIndex] = { ...terms[upcomingIndex], is_upcoming: true };
  return terms;
}

/**
 * uses_plus_minus mirrors what this app already models per real institution
 * (see TAMU current-grade options: exactly A-F, no plus/minus, vs. SMU's own
 * plus/minus scale) -- kept consistent rather than inventing a third scheme.
 */
const GRADING_SCHEMAS: Record<'smu' | 'tamu', GradingSchema> = {
  smu: {
    institutionId: null,
    usesPlusMinus: true,
    grades: [
      { letter: 'A', points: 4.0, counts_toward_gpa: true, counts_toward_credit: true },
      { letter: 'A-', points: 3.7, counts_toward_gpa: true, counts_toward_credit: true },
      { letter: 'B+', points: 3.3, counts_toward_gpa: true, counts_toward_credit: true },
      { letter: 'B', points: 3.0, counts_toward_gpa: true, counts_toward_credit: true },
      { letter: 'B-', points: 2.7, counts_toward_gpa: true, counts_toward_credit: true },
      { letter: 'C+', points: 2.3, counts_toward_gpa: true, counts_toward_credit: true },
      { letter: 'C', points: 2.0, counts_toward_gpa: true, counts_toward_credit: true },
      { letter: 'C-', points: 1.7, counts_toward_gpa: true, counts_toward_credit: true },
      { letter: 'D', points: 1.0, counts_toward_gpa: true, counts_toward_credit: true },
      { letter: 'F', points: 0.0, counts_toward_gpa: true, counts_toward_credit: false },
      { letter: 'W', points: null, counts_toward_gpa: false, counts_toward_credit: false },
    ],
  },
  tamu: {
    institutionId: null,
    usesPlusMinus: false,
    grades: [
      { letter: 'A', points: 4.0, counts_toward_gpa: true, counts_toward_credit: true },
      { letter: 'B', points: 3.0, counts_toward_gpa: true, counts_toward_credit: true },
      { letter: 'C', points: 2.0, counts_toward_gpa: true, counts_toward_credit: true },
      { letter: 'D', points: 1.0, counts_toward_gpa: true, counts_toward_credit: true },
      { letter: 'F', points: 0.0, counts_toward_gpa: true, counts_toward_credit: false },
      { letter: 'W', points: null, counts_toward_gpa: false, counts_toward_credit: false },
      { letter: 'I', points: null, counts_toward_gpa: false, counts_toward_credit: false },
    ],
  },
};

type CatalogRow = Omit<CatalogSearchResult, 'id'>;

const SMU_CATALOG: CatalogRow[] = [
  { code: 'CS 1341', title: 'Principles of Computer Science I', department: 'Computer Science', course_level: 1000, credit_min: 3, credit_max: 3 },
  { code: 'CS 1342', title: 'Principles of Computer Science II', department: 'Computer Science', course_level: 1000, credit_min: 3, credit_max: 3 },
  { code: 'CS 1311', title: 'AI for Every Mustang', department: 'Computer Science', course_level: 1000, credit_min: 3, credit_max: 3 },
  { code: 'CS 2340', title: 'Computer Organization', department: 'Computer Science', course_level: 2000, credit_min: 3, credit_max: 3 },
  { code: 'CS 2353', title: 'Programming with Data Structures', department: 'Computer Science', course_level: 2000, credit_min: 3, credit_max: 3 },
  { code: 'CS 3341', title: 'Algorithm Engineering and Analysis', department: 'Computer Science', course_level: 3000, credit_min: 3, credit_max: 3 },
  { code: 'CS 3353', title: 'Software Engineering', department: 'Computer Science', course_level: 3000, credit_min: 3, credit_max: 3 },
  { code: 'CS 3377', title: 'Systems Programming in UNIX and C', department: 'Computer Science', course_level: 3000, credit_min: 3, credit_max: 3 },
  { code: 'CS 4340', title: 'Networks and Distributed Processing', department: 'Computer Science', course_level: 4000, credit_min: 3, credit_max: 3 },
  { code: 'CS 5323', title: 'Programming Languages', department: 'Computer Science', course_level: 5000, credit_min: 3, credit_max: 3 },
  { code: 'CS 5328', title: 'Artificial Intelligence', department: 'Computer Science', course_level: 5000, credit_min: 3, credit_max: 3 },
  { code: 'CS 5330', title: 'Machine Learning', department: 'Computer Science', course_level: 5000, credit_min: 3, credit_max: 3 },
  { code: 'CS 5343', title: 'Analysis of Algorithms', department: 'Computer Science', course_level: 5000, credit_min: 3, credit_max: 3 },
  { code: 'CS 5344', title: 'Operating Systems', department: 'Computer Science', course_level: 5000, credit_min: 3, credit_max: 3 },
  { code: 'CS 5351', title: 'Database Systems', department: 'Computer Science', course_level: 5000, credit_min: 3, credit_max: 3 },
  { code: 'MATH 1337', title: 'Calculus I', department: 'Mathematics', course_level: 1000, credit_min: 3, credit_max: 3 },
  { code: 'MATH 1338', title: 'Calculus II', department: 'Mathematics', course_level: 1000, credit_min: 3, credit_max: 3 },
  { code: 'MATH 3304', title: 'Introduction to Linear Algebra', department: 'Mathematics', course_level: 3000, credit_min: 3, credit_max: 3 },
  { code: 'ENGR 1199', title: 'First-Year Engineering Seminar', department: 'Lyle School of Engineering', course_level: 1000, credit_min: 1, credit_max: 1 },
  { code: 'ENGR 2101', title: 'Interdisciplinary Project: Design Process and Teams', department: 'Lyle School of Engineering', course_level: 2000, credit_min: 1, credit_max: 1 },
  { code: 'ENGR 2111', title: 'Leadership and Mentorship for Engineers', department: 'Lyle School of Engineering', course_level: 2000, credit_min: 1, credit_max: 1 },
  { code: 'ENGR 3101', title: 'Engineering Ethics', department: 'Lyle School of Engineering', course_level: 3000, credit_min: 1, credit_max: 1 },
  { code: 'ENGR 4101', title: 'Senior Design Capstone Seminar', department: 'Lyle School of Engineering', course_level: 4000, credit_min: 1, credit_max: 1 },
  { code: 'CEE 2302', title: 'Introduction to Civil and Environmental Engineering', department: 'Civil and Environmental Engineering', course_level: 2000, credit_min: 3, credit_max: 3 },
  { code: 'BIOL 1301', title: 'General Biology I', department: 'Biological Sciences', course_level: 1000, credit_min: 3, credit_max: 3 },
  { code: 'BIOL 1101', title: 'General Biology I Laboratory', department: 'Biological Sciences', course_level: 1000, credit_min: 1, credit_max: 1 },
  { code: 'BIOL 1302', title: 'General Biology II', department: 'Biological Sciences', course_level: 1000, credit_min: 3, credit_max: 3 },
  { code: 'BIOL 1102', title: 'General Biology II Laboratory', department: 'Biological Sciences', course_level: 1000, credit_min: 1, credit_max: 1 },
];

const TAMU_CATALOG: CatalogRow[] = [
  { code: 'CSCE 121', title: 'Introduction to Program Design and Concepts', department: 'Computer Science and Engineering', course_level: 100, credit_min: 4, credit_max: 4 },
  { code: 'CSCE 181', title: 'Introduction to Computing', department: 'Computer Science and Engineering', course_level: 100, credit_min: 1, credit_max: 1 },
  { code: 'CSCE 221', title: 'Data Structures and Algorithms', department: 'Computer Science and Engineering', course_level: 200, credit_min: 4, credit_max: 4 },
  { code: 'CSCE 222', title: 'Discrete Structures for Computing', department: 'Computer Science and Engineering', course_level: 200, credit_min: 3, credit_max: 3 },
  { code: 'CSCE 312', title: 'Computer Organization', department: 'Computer Science and Engineering', course_level: 300, credit_min: 4, credit_max: 4 },
  { code: 'CSCE 313', title: 'Introduction to Computer Systems', department: 'Computer Science and Engineering', course_level: 300, credit_min: 3, credit_max: 3 },
  { code: 'CSCE 314', title: 'Programming Languages', department: 'Computer Science and Engineering', course_level: 300, credit_min: 3, credit_max: 3 },
  { code: 'CSCE 350', title: 'Programming Studio', department: 'Computer Science and Engineering', course_level: 300, credit_min: 3, credit_max: 3 },
  { code: 'CSCE 411', title: 'Design and Analysis of Algorithms', department: 'Computer Science and Engineering', course_level: 400, credit_min: 3, credit_max: 3 },
  { code: 'CSCE 431', title: 'Software Engineering', department: 'Computer Science and Engineering', course_level: 400, credit_min: 3, credit_max: 3 },
  { code: 'MATH 151', title: 'Engineering Mathematics I', department: 'Mathematics', course_level: 100, credit_min: 4, credit_max: 4 },
  { code: 'MATH 152', title: 'Engineering Mathematics II', department: 'Mathematics', course_level: 100, credit_min: 4, credit_max: 4 },
  { code: 'MATH 251', title: 'Engineering Mathematics III', department: 'Mathematics', course_level: 200, credit_min: 3, credit_max: 3 },
  { code: 'CHEM 107', title: 'General Chemistry for Engineering Students', department: 'Chemistry', course_level: 100, credit_min: 3, credit_max: 3 },
  { code: 'PHYS 218', title: 'Mechanics', department: 'Physics and Astronomy', course_level: 200, credit_min: 4, credit_max: 4 },
  { code: 'PHYS 208', title: 'Electricity and Magnetism', department: 'Physics and Astronomy', course_level: 200, credit_min: 4, credit_max: 4 },
  { code: 'ENGR 102', title: 'Engineering Lab I', department: 'Engineering', course_level: 100, credit_min: 2, credit_max: 2 },
  { code: 'ENGR 216', title: 'Electrical and Computer Engineering Fundamentals', department: 'Electrical and Computer Engineering', course_level: 200, credit_min: 4, credit_max: 4 },
  { code: 'ECEN 214', title: 'Electrical Circuit Theory', department: 'Electrical and Computer Engineering', course_level: 200, credit_min: 4, credit_max: 4 },
];

const GENERIC_CATALOG: CatalogRow[] = [
  { code: 'ENGL 1301', title: 'Composition and Rhetoric', department: 'English', course_level: 1000, credit_min: 3, credit_max: 3 },
  { code: 'HIST 1301', title: 'United States History I', department: 'History', course_level: 1000, credit_min: 3, credit_max: 3 },
  { code: 'PSYC 1300', title: 'Introduction to Psychology', department: 'Psychology', course_level: 1000, credit_min: 3, credit_max: 3 },
];

function catalogFor(institution: string | null): CatalogRow[] {
  const normalized = (institution ?? '').toLowerCase();
  if (normalized.includes('southern methodist')) return SMU_CATALOG;
  if (normalized.includes('texas a&m') || normalized.includes('texas a & m')) return TAMU_CATALOG;
  return GENERIC_CATALOG;
}

export function buildDemoGradingSchema(institution: string | null): GradingSchema {
  const normalized = (institution ?? '').toLowerCase();
  if (normalized.includes('texas a&m') || normalized.includes('texas a & m')) return GRADING_SCHEMAS.tamu;
  return GRADING_SCHEMAS.smu;
}

/** Prefix match against code or title, matching the real route's own
 * "Search matches the start of a course code or title" behavior. */
export function searchDemoCatalog(institution: string | null, query: string): CatalogSearchResult[] {
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) return [];
  return catalogFor(institution)
    .filter(
      (row) =>
        row.code.toLowerCase().replace(/\s+/g, '').startsWith(normalizedQuery.replace(/\s+/g, ''))
        || row.title.toLowerCase().startsWith(normalizedQuery),
    )
    .map((row) => ({ ...row, id: row.code }));
}
