import {
  TERMS_URL,
  PLANNED_COURSES_URL,
  PENDING_FINAL_GRADES_URL,
  GRADING_SCHEMA_URL,
  catalogSearchUrl,
  courseRecordUrl,
  finalizeCourseUrl,
  normalizeGradingSchemaPayload,
  normalizePendingFinalGradesPayload,
  normalizePlannedPayload,
  normalizeSearchPayload,
  normalizeTermsPayload,
  plannedListUrl,
  plannedRemoveUrl,
} from '../lib/termPlanning.mjs';
import type {
  AddedCourseResult,
  NormalizedGradingSchema,
  NormalizedPendingFinalGrades,
  NormalizedPlanned,
  NormalizedSearch,
  NormalizedTerms,
} from '../lib/termPlanning.mjs';

/**
 * Same shape as api/transcript.ts's send, minus the timeout parameter: none of
 * these routes runs AI work or reconciliation, so none of them has the cold
 * start the confirm routes budget for. They are plain reads and one small
 * insert.
 */
async function send(url: string, init: RequestInit): Promise<{ status: number; body: unknown }> {
  try {
    const response = await fetch(url, init);
    let body: unknown = null;
    try { body = await response.json(); } catch { /* normalizers accept null */ }
    return { status: response.status, body };
  } catch {
    return { status: 0, body: null };
  }
}

const auth = (token: string) => ({ Accept: 'application/json', Authorization: `Bearer ${token}` });

export async function fetchTerms(token: string): Promise<NormalizedTerms> {
  const { status, body } = await send(TERMS_URL, { method: 'GET', headers: auth(token) });
  return normalizeTermsPayload(status, body);
}

export async function fetchPlannedCourses(
  token: string,
  termId?: string | null,
): Promise<NormalizedPlanned> {
  const { status, body } = await send(plannedListUrl(termId), {
    method: 'GET',
    headers: auth(token),
  });
  return normalizePlannedPayload(status, body);
}

export interface AddPlannedCourseInput {
  course_code: string;
  year?: number | null;
  season?: string | null;
  term_label?: string | null;
  title?: string | null;
  credit_hours?: number | null;
  catalog_course_id?: string | null;
}

/**
 * The response's `planned_course` key is either a planned_courses row
 * (kind: 'planned') or, when the term is already inside its activation
 * window, a course_records row written directly as in-progress
 * (kind: 'in_progress') -- see lifecycle.add_course_respecting_activation.
 * The key name stays 'planned_course' on the wire (the route is still "plan a
 * course"); only the payload shape branches on `kind`.
 */
export async function addPlannedCourse(
  token: string,
  input: AddPlannedCourseInput,
): Promise<{ ok: boolean; course: AddedCourseResult | null; message: string | null }> {
  const { status, body } = await send(PLANNED_COURSES_URL, {
    method: 'POST',
    headers: { ...auth(token), 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
  if (status === 200 && body && typeof body === 'object' && 'planned_course' in body) {
    return {
      ok: true,
      course: (body as { planned_course: AddedCourseResult }).planned_course,
      message: null,
    };
  }
  const detail =
    body && typeof body === 'object' && 'detail' in body
      ? String((body as { detail: unknown }).detail)
      : 'Could not add that course to your plan.';
  return { ok: false, course: null, message: detail };
}

export async function removePlannedCourse(token: string, id: string): Promise<{ ok: boolean }> {
  const { status } = await send(plannedRemoveUrl(id), { method: 'DELETE', headers: auth(token) });
  // 404 counts as removed: the row is gone either way, and surfacing an error
  // for "it was already not there" would be a worse answer to the same state.
  return { ok: status === 200 || status === 404 };
}

export async function searchCatalog(token: string, query: string): Promise<NormalizedSearch> {
  const { status, body } = await send(catalogSearchUrl(query), {
    method: 'GET',
    headers: auth(token),
  });
  return normalizeSearchPayload(status, body);
}

export async function fetchGradingSchema(token: string): Promise<NormalizedGradingSchema> {
  const { status, body } = await send(GRADING_SCHEMA_URL, { method: 'GET', headers: auth(token) });
  return normalizeGradingSchemaPayload(status, body);
}

export async function fetchPendingFinalGrades(token: string): Promise<NormalizedPendingFinalGrades> {
  const { status, body } = await send(PENDING_FINAL_GRADES_URL, {
    method: 'GET',
    headers: auth(token),
  });
  return normalizePendingFinalGradesPayload(status, body);
}

export async function finalizeCourseGrade(
  token: string,
  courseId: string,
  letterGrade: string,
): Promise<{ ok: boolean; message: string | null }> {
  const { status, body } = await send(finalizeCourseUrl(courseId), {
    method: 'POST',
    headers: { ...auth(token), 'Content-Type': 'application/json' },
    body: JSON.stringify({ letter_grade: letterGrade }),
  });
  if (status === 200) return { ok: true, message: null };
  const detail =
    body && typeof body === 'object' && 'detail' in body
      ? String((body as { detail: unknown }).detail)
      : 'Could not save that grade.';
  return { ok: false, message: detail };
}

export interface EditInProgressCourseInput {
  course_code?: string;
  title?: string | null;
  term_id?: string | null;
  credit_hours?: number | null;
  letter_grade?: string | null;
  status?: 'dropped';
}

export async function editInProgressCourse(
  token: string,
  courseId: string,
  input: EditInProgressCourseInput,
): Promise<{ ok: boolean; message: string | null }> {
  const { status, body } = await send(courseRecordUrl(courseId), {
    method: 'PATCH',
    headers: { ...auth(token), 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
  if (status === 200) return { ok: true, message: null };
  const detail =
    body && typeof body === 'object' && 'detail' in body
      ? String((body as { detail: unknown }).detail)
      : 'Could not update that course.';
  return { ok: false, message: detail };
}
