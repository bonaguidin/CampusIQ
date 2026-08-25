const CAREER_OPTIMIZE_URL = '/api/v2/student/me/schedule/career-optimize';
const STATUSES = new Set(['OPTIMIZED', 'PARTIAL', 'FALLBACK', 'SKIPPED']);
const BASES = new Set(['CAREER_RANKED', 'ACADEMIC_DEFAULT']);
const CACHE_STATUSES = new Set(['HIT', 'MISS', 'BYPASSED']);

export class CareerOptimizationError extends Error {
  constructor(code, message = 'Career optimization is unavailable.') {
    super(message);
    this.name = 'CareerOptimizationError';
    this.code = code;
  }
}

function isRecord(value) {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isSchedule(value) {
  if (!isRecord(value) || !Array.isArray(value.terms) || !Array.isArray(value.unscheduled)) return false;
  return typeof value.student_id === 'string'
    && typeof value.program_id === 'string'
    && (value.status === 'SCHEDULED' || value.status === 'ERROR')
    && (value.failure === null || isRecord(value.failure));
}

function isRanking(value) {
  return isRecord(value)
    && typeof value.requirement_group_id === 'string'
    && Array.isArray(value.ranked_candidates)
    && value.ranked_candidates.every((candidate) => isRecord(candidate)
      && typeof candidate.candidate_id === 'string'
      && Number.isInteger(candidate.rank)
      && typeof candidate.ranking_reason === 'string'
      && typeof candidate.skill_alignment_explanation === 'string');
}

export function isCareerOptimizedScheduleResponse(value) {
  if (!isRecord(value)) return false;
  return value.feature === 'CAREER_OPTIMIZED_SCHEDULE'
    && STATUSES.has(value.status)
    && BASES.has(value.selection_basis)
    && (typeof value.target_role === 'string' || value.target_role === null)
    && (typeof value.fingerprint === 'string' || value.fingerprint === null)
    && typeof value.generated_at === 'string'
    && CACHE_STATUSES.has(value.cache_status)
    && isSchedule(value.academic_schedule)
    && isSchedule(value.optimized_schedule)
    && Array.isArray(value.requirement_rankings)
    && value.requirement_rankings.every(isRanking)
    && Array.isArray(value.ranking_failures)
    && value.ranking_failures.every((failure) => isRecord(failure)
      && typeof failure.requirement_group_id === 'string'
      && typeof failure.requirement_name === 'string'
      && typeof failure.error_code === 'string'
      && typeof failure.detail === 'string')
    && typeof value.ranking_prompt_version === 'string'
    && typeof value.resolved_model === 'string'
    && (typeof value.summary === 'string' || value.summary === null);
}

export async function fetchCareerOptimizedSchedule(token, request = {}) {
  const payload = {
    ...(request.target_role ? { target_role: request.target_role } : {}),
    force_refresh: request.force_refresh ?? false,
  };
  let response;
  try {
    response = await fetch(CAREER_OPTIMIZE_URL, {
      method: 'POST',
      headers: {
        Accept: 'application/json',
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    });
  } catch {
    throw new Error('Career optimization is unavailable.');
  }

  let body = null;
  try { body = await response.json(); } catch { /* handled below */ }
  if (response.status === 200) {
    if (isCareerOptimizedScheduleResponse(body)) return body;
    throw new Error('Career optimization returned an invalid response.');
  }
  const detail = isRecord(body) && 'detail' in body ? body.detail : null;
  if (isRecord(detail) && typeof detail.code === 'string') {
    throw new CareerOptimizationError(detail.code);
  }
  throw new CareerOptimizationError(
    'UNKNOWN_ERROR',
    typeof detail === 'string' ? detail : 'Career optimization is unavailable.',
  );
}
