import {
  TRANSCRIPT_CONFIRM_URL,
  TRANSCRIPT_REVIEW_URL,
  TRANSCRIPT_UPLOAD_URL,
  normalizeTranscriptConfirm,
  normalizeTranscriptPatch,
  normalizeTranscriptReview,
  normalizeTranscriptUpload,
  transcriptEditUrl,
} from '../lib/transcriptApi.mjs';
import type { TranscriptConfirmResult, TranscriptPatchResult, TranscriptReviewResult, TranscriptUploadResult } from '../lib/transcriptApi.mjs';

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

export async function uploadTranscript(token: string, file: File): Promise<TranscriptUploadResult> {
  const form = new FormData();
  form.append('file', file);
  const { status, body } = await send(TRANSCRIPT_UPLOAD_URL, { method: 'POST', headers: auth(token), body: form });
  return normalizeTranscriptUpload(status, body);
}

export async function fetchTranscriptReview(token: string): Promise<TranscriptReviewResult> {
  const { status, body } = await send(TRANSCRIPT_REVIEW_URL, { method: 'GET', headers: auth(token) });
  return normalizeTranscriptReview(status, body);
}

export async function patchTranscriptRecord(token: string, id: string, changes: Record<string, unknown>): Promise<TranscriptPatchResult> {
  const { status, body } = await send(transcriptEditUrl(id), { method: 'PATCH', headers: { ...auth(token), 'Content-Type': 'application/json' }, body: JSON.stringify(changes) });
  return normalizeTranscriptPatch(status, body);
}

export async function confirmTranscript(token: string): Promise<TranscriptConfirmResult> {
  const { status, body } = await send(TRANSCRIPT_CONFIRM_URL, { method: 'POST', headers: auth(token) });
  return normalizeTranscriptConfirm(status, body);
}
