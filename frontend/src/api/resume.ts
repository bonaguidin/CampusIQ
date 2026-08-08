// Fetch layer for the resume flow.
//
// Every call is a same-origin relative path so it goes through the Vercel
// proxy (frontend/api/proxy.mjs), which is the only path that can reach the
// backend: it attaches the server-only X-CampusIQ-Proxy-Secret, and the
// backend's CORS allow_headers does not include Authorization, so a direct
// cross-origin call from the browser would fail preflight regardless.
//
// Mirrors fetchMeProfile's contract in lib/studentAccount.ts: return a
// status/data pair, never throw on a non-2xx. Callers branch on the normalized
// `kind`, and a thrown error would collapse fifteen distinct outcomes into one.
// The only throw path is a genuine network failure, handled here as a
// synthetic status 0.

import {
  CONFIRM_URL,
  REVIEW_URL,
  UPLOAD_URL,
  normalizeConfirmResponse,
  normalizePatchResponse,
  normalizeReviewResponse,
  normalizeUploadResponse,
  reviewEditUrl,
} from '../lib/resumeApi.mjs';
import type {
  NormalizedConfirm,
  NormalizedPatch,
  NormalizedReview,
  NormalizedUpload,
} from '../lib/resumeApi.mjs';

/** Status 0 means "the request never reached the server". */
const NETWORK_FAILURE = 0;

interface RawResult {
  status: number;
  body: unknown;
}

async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    // A 502 from the platform, or an empty body, is not JSON. The normalizers
    // all tolerate an absent body.
    return null;
  }
}

async function send(url: string, init: RequestInit): Promise<RawResult> {
  try {
    const response = await fetch(url, init);
    return { status: response.status, body: await readJson(response) };
  } catch {
    return { status: NETWORK_FAILURE, body: null };
  }
}

function authHeaders(accessToken: string): Record<string, string> {
  return { Accept: 'application/json', Authorization: `Bearer ${accessToken}` };
}

export async function uploadResume(
  accessToken: string,
  file: File,
): Promise<NormalizedUpload> {
  const form = new FormData();
  // Field name must be exactly "file" -- it is the FastAPI parameter name, and
  // anything else is a 422 from request validation.
  form.append('file', file);

  // NOTE: no Content-Type header. Setting it by hand omits the multipart
  // boundary the browser generates, which makes the body unparseable at the
  // backend. The proxy forwards the inbound Content-Type verbatim precisely so
  // the generated boundary survives.
  const { status, body } = await send(UPLOAD_URL, {
    method: 'POST',
    headers: authHeaders(accessToken),
    body: form,
  });

  return normalizeUploadResponse(status, body);
}

export async function fetchCareerReview(accessToken: string): Promise<NormalizedReview> {
  const { status, body } = await send(REVIEW_URL, {
    method: 'GET',
    headers: authHeaders(accessToken),
  });
  return normalizeReviewResponse(status, body);
}

export async function patchCareerRow(
  accessToken: string,
  table: string,
  id: string,
  changes: Record<string, unknown>,
): Promise<NormalizedPatch> {
  const { status, body } = await send(reviewEditUrl(table, id), {
    method: 'PATCH',
    headers: { ...authHeaders(accessToken), 'Content-Type': 'application/json' },
    body: JSON.stringify(changes),
  });
  return normalizePatchResponse(status, body);
}

export async function confirmCareerRecords(accessToken: string): Promise<NormalizedConfirm> {
  // No body: the backend treats an absent/empty selection as "confirm
  // everything still unconfirmed", which is this stage's only mode.
  const { status, body } = await send(CONFIRM_URL, {
    method: 'POST',
    headers: authHeaders(accessToken),
  });
  return normalizeConfirmResponse(status, body);
}
