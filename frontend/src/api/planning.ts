import {
  TERMS_URL,
  PLANNED_COURSES_URL,
  catalogSearchUrl,
  normalizePlannedPayload,
  normalizeSearchPayload,
  normalizeTermsPayload,
  plannedListUrl,
  plannedRemoveUrl,
} from '../lib/termPlanning.mjs';
import type {
  NormalizedPlanned,
  NormalizedSearch,
  NormalizedTerms,
  PlannedCourse,
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

export async function addPlannedCourse(
  token: string,
  input: AddPlannedCourseInput,
): Promise<{ ok: boolean; plannedCourse: PlannedCourse | null; message: string | null }> {
  const { status, body } = await send(PLANNED_COURSES_URL, {
    method: 'POST',
    headers: { ...auth(token), 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
  if (status === 200 && body && typeof body === 'object' && 'planned_course' in body) {
    return {
      ok: true,
      plannedCourse: (body as { planned_course: PlannedCourse }).planned_course,
      message: null,
    };
  }
  const detail =
    body && typeof body === 'object' && 'detail' in body
      ? String((body as { detail: unknown }).detail)
      : 'Could not add that course to your plan.';
  return { ok: false, plannedCourse: null, message: detail };
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
