import type { AcademicCourse } from '../types/studentIntelligenceProfile';
import type { PlannedCourse } from '../lib/termPlanning.mjs';

/**
 * Per-slug, in-memory-only mutable state for GPA Calculator's demo branch --
 * planned courses added/removed, and course-record edits (drop, current
 * grade) made through TermPlanner. Nothing here ever leaves the tab: no
 * fetch, no localStorage, gone on refresh. This is the single source of
 * truth the demo branches of frontend/src/api/planning.ts read and write;
 * DashboardPage re-syncs its own `courses` state from
 * snapshotDemoCourseRecords() after any mutation, the same way a real
 * account's onCourseRecordsChanged triggers a server profile re-fetch.
 */

interface DemoPlanningState {
  courseRecords: AcademicCourse[];
  plannedCourses: PlannedCourse[];
  nextPlannedId: number;
  institution: string | null;
}

const stores = new Map<string, DemoPlanningState>();

function getStore(slug: string): DemoPlanningState {
  let store = stores.get(slug);
  if (!store) {
    store = { courseRecords: [], plannedCourses: [], nextPlannedId: 1, institution: null };
    stores.set(slug, store);
  }
  return store;
}

/** Seeds a slug's course records + institution exactly once (first call
 * after login/mount for that slug); later calls are a no-op so an in-tab
 * edit is never silently reverted by a re-render re-seeding from the
 * original profile. */
export function ensureDemoPlanningStore(
  slug: string,
  seedCourses: AcademicCourse[],
  institution: string | null,
): void {
  if (stores.has(slug)) return;
  stores.set(slug, {
    courseRecords: seedCourses.map((course) => ({ ...course })),
    plannedCourses: [],
    nextPlannedId: 1,
    institution,
  });
}

export function getDemoInstitution(slug: string): string | null {
  return getStore(slug).institution;
}

export function snapshotDemoCourseRecords(slug: string): AcademicCourse[] {
  return getStore(slug).courseRecords.slice();
}

export function snapshotDemoPlannedCourses(slug: string): PlannedCourse[] {
  return getStore(slug).plannedCourses.slice();
}

export interface AddDemoPlannedCourseInput {
  course_code: string;
  title?: string | null;
  credit_hours?: number | null;
  catalog_course_id?: string | null;
}

/** Always returns kind: 'planned' -- unlike the real route, the demo store
 * doesn't model the 30-day activation-window edge case (a planned course
 * silently promoted straight to in_progress). Not essential to a demo
 * illustration, and skipping it keeps this store's mutation surface small. */
export function addDemoPlannedCourse(slug: string, input: AddDemoPlannedCourseInput): PlannedCourse {
  const store = getStore(slug);
  const course: PlannedCourse = {
    id: `demo-planned-${slug}-${store.nextPlannedId}`,
    term_id: null,
    course_code: input.course_code,
    title: input.title ?? null,
    credit_hours: input.credit_hours ?? null,
    catalog_course_id: input.catalog_course_id ?? null,
    created_at: new Date().toISOString(),
    kind: 'planned',
  };
  store.nextPlannedId += 1;
  store.plannedCourses = [...store.plannedCourses, course];
  return course;
}

/** Always succeeds, mirroring the real route's own 404-counts-as-removed
 * idempotency ("the row is gone either way"). */
export function removeDemoPlannedCourse(slug: string, id: string): void {
  const store = getStore(slug);
  store.plannedCourses = store.plannedCourses.filter((course) => course.id !== id);
}

export interface EditDemoCourseRecordInput {
  letter_grade?: string | null;
  status?: 'dropped';
}

export function editDemoCourseRecord(
  slug: string,
  courseId: string,
  input: EditDemoCourseRecordInput,
): boolean {
  const store = getStore(slug);
  const index = store.courseRecords.findIndex((course) => course.id === courseId);
  if (index === -1) return false;
  const current = store.courseRecords[index];
  const updated: AcademicCourse = { ...current };
  if (input.letter_grade !== undefined) updated.letter_grade = input.letter_grade;
  if (input.status === 'dropped') updated.status = 'dropped';
  store.courseRecords = [
    ...store.courseRecords.slice(0, index),
    updated,
    ...store.courseRecords.slice(index + 1),
  ];
  return true;
}
