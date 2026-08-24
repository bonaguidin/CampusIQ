import assert from 'node:assert/strict';
import test from 'node:test';

import { fetchTechnicalElectiveCandidates } from '../src/api/technicalElectives.mjs';

test('technical elective candidates use the authenticated read-only route', async (t) => {
  const calls = [];
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    calls.push({ url, init });
    return new Response(JSON.stringify({ candidates: [] }), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    });
  });
  await fetchTechnicalElectiveCandidates({ slug: null, accessToken: 'session-token' });
  assert.equal(calls[0].url, '/api/v2/student/me/degree-plan/technical-electives');
  assert.equal(calls[0].init.method, 'GET');
  assert.equal(calls[0].init.headers.Authorization, 'Bearer session-token');
});

test('technical elective candidates surface backend detail', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => new Response(
    JSON.stringify({ detail: 'Local candidate failure.' }),
    { status: 502, headers: { 'Content-Type': 'application/json' } },
  ));
  await assert.rejects(
    () => fetchTechnicalElectiveCandidates({ slug: null, accessToken: 'session-token' }),
    /Local candidate failure\./,
  );
});

test('technical elective candidates use the demo route when a slug identity is supplied, with no Authorization header', async (t) => {
  const calls = [];
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    calls.push({ url, init });
    return new Response(JSON.stringify({ candidates: [] }), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    });
  });
  await fetchTechnicalElectiveCandidates({ slug: 'ethanBrooks', accessToken: null });
  assert.equal(calls[0].url, '/api/students/ethanBrooks/degree-plan/technical-electives');
  assert.equal(calls[0].init.headers.Authorization, undefined);
});
