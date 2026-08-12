import assert from 'node:assert/strict'
import test from 'node:test'

import { createProxyHandler } from '../api/proxy.mjs'

const REQUEST_URL = 'https://gradusiq.example/api/proxy?student=jordanReyes&feature=gap'

test('server proxy rejects missing configuration without forwarding', async () => {
  let forwarded = false
  const handler = createProxyHandler({
    env: {},
    fetchImpl: async () => {
      forwarded = true
      return new Response()
    },
  })

  const response = await handler.fetch(new Request(REQUEST_URL, { method: 'POST' }))

  assert.equal(response.status, 503)
  assert.equal(forwarded, false)
})

test('server proxy validates method, student slug, and feature', async () => {
  const handler = createProxyHandler({ env: {}, fetchImpl: async () => new Response() })

  // Methods the proxy carries for no route at all are rejected outright.
  assert.equal(
    (await handler.fetch(new Request(REQUEST_URL, { method: 'PUT' }))).status,
    405,
  )
  // DELETE became a method the proxy accepts when the planned-course removal
  // target was added, so it no longer stops at the 405 method gate. It must
  // still never reach a slug-addressed AI route: the slug branch admits only
  // GET and POST, so this is a 400 rather than a forwarded request.
  let forwardedDelete = false
  const deleteHandler = createProxyHandler({
    env: { GRADUSIQ_BACKEND_URL: 'https://backend.example', GRADUSIQ_PROXY_SECRET: 's' },
    fetchImpl: async () => {
      forwardedDelete = true
      return new Response()
    },
  })
  assert.equal(
    (await deleteHandler.fetch(new Request(REQUEST_URL, { method: 'DELETE' }))).status,
    400,
  )
  assert.equal(forwardedDelete, false)
  // GET is now a valid method, but only for read features -- a GET naming an
  // AI feature is a method/feature mismatch (400), never a triggered AI call.
  assert.equal((await handler.fetch(new Request(REQUEST_URL))).status, 400)
  assert.equal(
    (
      await handler.fetch(
        new Request('https://gradusiq.example/api/proxy?student=../secret&feature=gap', {
          method: 'POST',
        }),
      )
    ).status,
    400,
  )
  assert.equal(
    (
      await handler.fetch(
        new Request('https://gradusiq.example/api/proxy?student=jordanReyes&feature=unknown', {
          method: 'POST',
        }),
      )
    ).status,
    400,
  )
})

test('server proxy attaches its secret and forwards only an allowlisted backend path', async () => {
  const calls = []
  const handler = createProxyHandler({
    env: {
      GRADUSIQ_BACKEND_URL: 'https://backend.example',
      GRADUSIQ_PROXY_SECRET: 'server-only-secret',
    },
    fetchImpl: async (url, options) => {
      calls.push({ url: url.toString(), options })
      return Response.json({ status: 'success' }, { status: 200 })
    },
  })

  const response = await handler.fetch(
    new Request(REQUEST_URL, {
      method: 'POST',
      headers: { 'X-GradusIQ-Proxy-Secret': 'browser-supplied-value' },
    }),
  )

  assert.equal(response.status, 200)
  assert.equal(calls.length, 1)
  assert.equal(calls[0].url, 'https://backend.example/api/students/jordanReyes/analyze/gap')
  assert.equal(calls[0].options.headers['X-GradusIQ-Proxy-Secret'], 'server-only-secret')
  assert.equal(JSON.stringify(calls[0].options).includes('browser-supplied-value'), false)
})

test('server proxy preserves sanitized backend status and handles transport failure', async () => {
  const env = {
    GRADUSIQ_BACKEND_URL: 'https://backend.example',
    GRADUSIQ_PROXY_SECRET: 'server-only-secret',
  }
  const rejected = createProxyHandler({
    env,
    fetchImpl: async () => Response.json({ detail: 'Unauthorized.' }, { status: 401 }),
  })
  const unavailable = createProxyHandler({
    env,
    fetchImpl: async () => {
      throw new Error('internal transport detail')
    },
  })

  assert.equal((await rejected.fetch(new Request(REQUEST_URL, { method: 'POST' }))).status, 401)
  const failed = await unavailable.fetch(new Request(REQUEST_URL, { method: 'POST' }))
  assert.equal(failed.status, 502)
  assert.deepEqual(await failed.json(), { detail: 'Analysis backend is unavailable.' })
})

const PROFILE_URL = 'https://gradusiq.example/api/proxy?student=jordanReyes&feature=profile'

test('server proxy forwards GET profile to the backend profile route with its secret', async () => {
  const calls = []
  const handler = createProxyHandler({
    env: {
      GRADUSIQ_BACKEND_URL: 'https://backend.example',
      GRADUSIQ_PROXY_SECRET: 'server-only-secret',
    },
    fetchImpl: async (url, options) => {
      calls.push({ url: url.toString(), options })
      return Response.json({ student: { name: 'Jordan Reyes' } }, { status: 200 })
    },
  })

  const response = await handler.fetch(new Request(PROFILE_URL, { method: 'GET' }))

  assert.equal(response.status, 200)
  assert.equal(calls.length, 1)
  assert.equal(calls[0].url, 'https://backend.example/api/students/jordanReyes/profile')
  assert.equal(calls[0].options.method, 'GET')
  assert.equal(calls[0].options.headers['X-GradusIQ-Proxy-Secret'], 'server-only-secret')
  // A GET must not carry a forwarded body.
  assert.equal(calls[0].options.body, undefined)
})

test('server proxy rejects a POST to the read-only profile feature', async () => {
  let forwarded = false
  const handler = createProxyHandler({
    env: {
      GRADUSIQ_BACKEND_URL: 'https://backend.example',
      GRADUSIQ_PROXY_SECRET: 'server-only-secret',
    },
    fetchImpl: async () => {
      forwarded = true
      return new Response()
    },
  })

  const response = await handler.fetch(new Request(PROFILE_URL, { method: 'POST' }))

  assert.equal(response.status, 400)
  assert.equal(forwarded, false)
})

test('server proxy still rejects a traversal slug on the profile route', async () => {
  const handler = createProxyHandler({
    env: {
      GRADUSIQ_BACKEND_URL: 'https://backend.example',
      GRADUSIQ_PROXY_SECRET: 'server-only-secret',
    },
    fetchImpl: async () => new Response(),
  })

  const response = await handler.fetch(
    new Request('https://gradusiq.example/api/proxy?student=../secret&feature=profile', {
      method: 'GET',
    }),
  )

  assert.equal(response.status, 400)
})

// ── Session-scoped /me targets ───────────────────────────────────────────────

const ME_ENV = {
  GRADUSIQ_BACKEND_URL: 'https://backend.example',
  GRADUSIQ_PROXY_SECRET: 'server-only-secret',
}

test('slug-addressed request still forwards NO Authorization, even if sent', async () => {
  const calls = []
  const handler = createProxyHandler({
    env: ME_ENV,
    fetchImpl: async (url, options) => {
      calls.push({ url: url.toString(), options })
      return Response.json({ ok: true }, { status: 200 })
    },
  })

  await handler.fetch(
    new Request(REQUEST_URL, {
      method: 'POST',
      headers: { Authorization: 'Bearer browser-supplied-token' },
    }),
  )

  assert.equal(calls.length, 1)
  assert.equal(calls[0].options.headers.Authorization, undefined)
  assert.equal(
    JSON.stringify(calls[0].options).includes('browser-supplied-token'),
    false,
  )
  // The proxy secret is still attached.
  assert.equal(calls[0].options.headers['X-GradusIQ-Proxy-Secret'], 'server-only-secret')
})

test('me-target request DOES forward a browser-supplied Authorization header', async () => {
  const calls = []
  const handler = createProxyHandler({
    env: ME_ENV,
    fetchImpl: async (url, options) => {
      calls.push({ url: url.toString(), options })
      return Response.json({ ok: true }, { status: 200 })
    },
  })

  await handler.fetch(
    new Request('https://gradusiq.example/api/proxy?target=me-analyze&feature=gap', {
      method: 'POST',
      headers: { Authorization: 'Bearer real-session-jwt' },
    }),
  )

  assert.equal(calls.length, 1)
  assert.equal(calls[0].url, 'https://backend.example/api/v2/student/me/analyze/gap')
  assert.equal(calls[0].options.headers.Authorization, 'Bearer real-session-jwt')
  assert.equal(calls[0].options.headers['X-GradusIQ-Proxy-Secret'], 'server-only-secret')
})

test('me-chat and me-profile reads/edits map to their backend paths with the right methods', async () => {
  const calls = []
  const handler = createProxyHandler({
    env: ME_ENV,
    fetchImpl: async (url, options) => {
      calls.push({ url: url.toString(), method: options.method })
      return Response.json({ ok: true }, { status: 200 })
    },
  })

  await handler.fetch(
    new Request('https://gradusiq.example/api/proxy?target=me-chat', {
      method: 'POST',
      headers: { Authorization: 'Bearer t' },
      body: JSON.stringify({ message: 'hi', history: [] }),
    }),
  )
  await handler.fetch(
    new Request('https://gradusiq.example/api/proxy?target=me-profile', {
      method: 'GET',
      headers: { Authorization: 'Bearer t' },
    }),
  )
  await handler.fetch(
    new Request('https://gradusiq.example/api/proxy?target=me-profile', {
      method: 'PATCH',
      headers: { Authorization: 'Bearer t', 'Content-Type': 'application/json' },
      body: JSON.stringify({ major_intended: 'N/A' }),
    }),
  )

  assert.deepEqual(calls, [
    { url: 'https://backend.example/api/v2/student/me/chat', method: 'POST' },
    { url: 'https://backend.example/api/v2/student/me/profile', method: 'GET' },
    { url: 'https://backend.example/api/v2/student/me/profile', method: 'PATCH' },
  ])
})

// ── me-resume-upload: binary body passthrough ────────────────────────────────

const UPLOAD_URL = 'https://gradusiq.example/api/proxy?target=me-resume-upload'

/**
 * Bytes that are NOT valid UTF-8, so a text round-trip is guaranteed to be
 * detectable rather than accidentally lossless.
 *
 *   0x25 0x50 0x44 0x46  -> "%PDF", a real PDF magic number
 *   0xFF 0xFE            -> never valid in UTF-8
 *   0x80, 0xC3 0x28      -> lone continuation byte / invalid 2-byte sequence
 *   0x00                 -> embedded NUL
 *
 * request.text() maps each invalid sequence to U+FFFD, which re-encodes to
 * 0xEF 0xBF 0xBD -- so a text-decoding proxy changes both the bytes and the
 * length. Asserting on exact bytes is what makes this test meaningful.
 */
const BINARY_BODY = new Uint8Array([
  0x25, 0x50, 0x44, 0x46, 0x2d, 0x31, 0x2e, 0x37,
  0xff, 0xfe, 0x80, 0xc3, 0x28, 0x00, 0x01, 0x02,
  0xde, 0xad, 0xbe, 0xef,
])

test('me-resume-upload forwards a binary body byte-identical', async () => {
  const calls = []
  const handler = createProxyHandler({
    env: ME_ENV,
    fetchImpl: async (url, options) => {
      calls.push({ url: url.toString(), options })
      return Response.json({ status: 'ok' }, { status: 200 })
    },
  })

  const response = await handler.fetch(
    new Request(UPLOAD_URL, {
      method: 'POST',
      headers: {
        Authorization: 'Bearer real-session-jwt',
        'Content-Type': 'application/pdf',
      },
      body: BINARY_BODY,
    }),
  )

  assert.equal(response.status, 200)
  assert.equal(calls.length, 1)
  assert.equal(calls[0].url, 'https://backend.example/api/v2/student/me/resume/upload')

  // The body must arrive as raw bytes, not a string.
  const forwarded = calls[0].options.body
  assert.ok(
    forwarded instanceof ArrayBuffer,
    `expected an ArrayBuffer body, got ${Object.prototype.toString.call(forwarded)}`,
  )

  // Byte-for-byte equality -- the actual assertion that catches the
  // UTF-8-decoding corruption bug.
  const received = new Uint8Array(forwarded)
  assert.equal(received.length, BINARY_BODY.length)
  assert.deepEqual(Array.from(received), Array.from(BINARY_BODY))

  // Belt and braces: prove the corrupted form is absent. A text round-trip
  // would have introduced the U+FFFD replacement byte sequence.
  assert.equal(received.includes(0xfd), false)
  assert.equal(received.includes(0xff), true)
})

test('me-resume-upload preserves the multipart Content-Type boundary exactly', async () => {
  const calls = []
  const handler = createProxyHandler({
    env: ME_ENV,
    fetchImpl: async (url, options) => {
      calls.push({ url: url.toString(), options })
      return Response.json({ status: 'ok' }, { status: 200 })
    },
  })

  const contentType =
    'multipart/form-data; boundary=----WebKitFormBoundary7MA4YWxkTrZu0gW'

  await handler.fetch(
    new Request(UPLOAD_URL, {
      method: 'POST',
      headers: { Authorization: 'Bearer t', 'Content-Type': contentType },
      body: BINARY_BODY,
    }),
  )

  assert.equal(calls.length, 1)
  // Exact string equality: dropping or rewriting the boundary parameter makes
  // the payload unparseable at the backend.
  assert.equal(calls[0].options.headers['Content-Type'], contentType)
  assert.match(calls[0].options.headers['Content-Type'], /boundary=/)
  // It must NOT have been defaulted to JSON.
  assert.notEqual(calls[0].options.headers['Content-Type'], 'application/json')
})

test('me-resume-upload forwards Authorization and the proxy secret', async () => {
  const calls = []
  const handler = createProxyHandler({
    env: ME_ENV,
    fetchImpl: async (url, options) => {
      calls.push({ url: url.toString(), options })
      return Response.json({ status: 'ok' }, { status: 200 })
    },
  })

  await handler.fetch(
    new Request(UPLOAD_URL, {
      method: 'POST',
      headers: {
        Authorization: 'Bearer real-session-jwt',
        'Content-Type': 'application/pdf',
      },
      body: BINARY_BODY,
    }),
  )

  assert.equal(calls.length, 1)
  assert.equal(calls[0].options.headers.Authorization, 'Bearer real-session-jwt')
  assert.equal(calls[0].options.headers['X-GradusIQ-Proxy-Secret'], 'server-only-secret')
})

test('me-resume-upload is POST-only and unaffected by the slug branch', async () => {
  let forwarded = false
  const handler = createProxyHandler({
    env: ME_ENV,
    fetchImpl: async () => {
      forwarded = true
      return new Response()
    },
  })

  const asGet = await handler.fetch(new Request(UPLOAD_URL, { method: 'GET' }))
  assert.equal(asGet.status, 400)
  assert.equal(forwarded, false)
})

test('adding a binary target leaves the JSON targets reading their body as text', async () => {
  // Guards the regression the new body branch could plausibly introduce:
  // me-chat must still forward a decoded JSON string, not an ArrayBuffer.
  const calls = []
  const handler = createProxyHandler({
    env: ME_ENV,
    fetchImpl: async (url, options) => {
      calls.push(options)
      return Response.json({ ok: true }, { status: 200 })
    },
  })

  const payload = JSON.stringify({ message: 'hi', history: [] })
  await handler.fetch(
    new Request('https://gradusiq.example/api/proxy?target=me-chat', {
      method: 'POST',
      headers: { Authorization: 'Bearer t', 'Content-Type': 'application/json' },
      body: payload,
    }),
  )

  assert.equal(calls.length, 1)
  assert.equal(typeof calls[0].body, 'string')
  assert.equal(calls[0].body, payload)
  assert.equal(calls[0].headers['Content-Type'], 'application/json')

  // And a body-less POST still forwards no body at all.
  await handler.fetch(
    new Request('https://gradusiq.example/api/proxy?target=me-analyze&feature=gap', {
      method: 'POST',
      headers: { Authorization: 'Bearer t' },
    }),
  )
  assert.equal(calls[1].body, undefined)
  // Unchanged default for JSON targets that send no Content-Type.
  assert.equal(calls[1].headers['Content-Type'], 'application/json')
})

test('transcript targets preserve auth, methods, paths, and binary upload bytes', async () => {
  const calls = []
  const handler = createProxyHandler({ env: ME_ENV, fetchImpl: async (url, options) => {
    calls.push({ url: url.toString(), options })
    return Response.json({ ok: true })
  } })
  const token = { Authorization: 'Bearer transcript-token' }
  await handler.fetch(new Request('https://gradusiq.example/api/proxy?target=me-transcript-upload', { method: 'POST', headers: { ...token, 'Content-Type': 'application/pdf' }, body: BINARY_BODY }))
  await handler.fetch(new Request('https://gradusiq.example/api/proxy?target=me-transcript-review', { method: 'GET', headers: token }))
  await handler.fetch(new Request('https://gradusiq.example/api/proxy?target=me-transcript-review-edit&id=11111111-1111-4111-8111-111111111111', { method: 'PATCH', headers: { ...token, 'Content-Type': 'application/json' }, body: '{"title":"Corrected"}' }))
  await handler.fetch(new Request('https://gradusiq.example/api/proxy?target=me-transcript-confirm', { method: 'POST', headers: token }))
  assert.deepEqual(calls.map((call) => call.url), [
    'https://backend.example/api/v2/student/me/transcript/upload',
    'https://backend.example/api/v2/student/me/transcript/review',
    'https://backend.example/api/v2/student/me/transcript/review/11111111-1111-4111-8111-111111111111',
    'https://backend.example/api/v2/student/me/transcript/confirm',
  ])
  assert.ok(calls[0].options.body instanceof ArrayBuffer)
  assert.equal(calls.every((call) => call.options.headers.Authorization === 'Bearer transcript-token'), true)
})

test('the target allowlist stays closed after adding me-resume-upload', async () => {
  let forwarded = false
  const handler = createProxyHandler({
    env: ME_ENV,
    fetchImpl: async () => {
      forwarded = true
      return new Response()
    },
  })

  // Near-misses on the new entry, plus an unrelated unknown target. None may
  // reach the backend, and none may inherit the binary branch.
  const rejected = [
    'me-resume',
    'me-resume-upload-x',
    'me-upload',
    'resume-upload',
    'ME-RESUME-UPLOAD',
    'me-danger',
    '__proto__',
    'constructor',
  ]

  for (const target of rejected) {
    const response = await handler.fetch(
      new Request(
        `https://gradusiq.example/api/proxy?target=${encodeURIComponent(target)}`,
        { method: 'POST', body: 'x' },
      ),
    )
    assert.equal(response.status, 400, `target=${target} should be rejected`)
  }

  assert.equal(forwarded, false)
})

test('inherited Object.prototype keys are rejected by the map itself, not by the method check', async () => {
  // WHY THIS IS NOT COVERED BY THE ALLOWLIST TEST ABOVE.
  //
  // With a plain object literal, ME_TARGETS['toString'] returns a truthy
  // inherited value, so `!spec` does not reject it. What rejects it is the
  // NEXT line -- `method !== spec.method` -- and only because spec.method
  // happens to be undefined. That is a coincidence, not a control.
  //
  // Polluting Object.prototype.method removes the coincidence: spec.method now
  // equals the request method, the method check passes, needsFeature is falsy
  // so the feature check is skipped, and an unvalidated target reaches
  // meBackendPath -- forwarded to the backend with the caller's bearer token
  // and the proxy secret attached. Verified against the pre-fix code, which
  // returned 200 and forwarded to /api/v2/student/me/analyze/.
  //
  // So this test isolates the guard: the ONLY thing that can reject these
  // requests is ME_TARGETS having no prototype to inherit from.
  const calls = []
  const handler = createProxyHandler({
    env: ME_ENV,
    fetchImpl: async (url, options) => {
      calls.push({ url: url.toString(), options })
      return Response.json({ ok: true }, { status: 200 })
    },
  })

  const inheritedKeys = ['toString', 'constructor', '__proto__', 'valueOf', 'hasOwnProperty']

  // Build every request BEFORE polluting, to keep the pollution window as
  // narrow as possible.
  const requests = inheritedKeys.map(
    (key) =>
      new Request(`https://gradusiq.example/api/proxy?target=${encodeURIComponent(key)}`, {
        method: 'POST',
        headers: { Authorization: 'Bearer victim-session-jwt' },
      }),
  )

  const results = []
  // eslint-disable-next-line no-extend-native -- deliberately simulating a
  // prototype-pollution primitive introduced elsewhere in the process.
  Object.prototype.method = 'POST'
  try {
    // Sanity-check the premise: the pollution really does make the method
    // check pass for an inherited key. If this ever stops holding, the test
    // below would pass vacuously.
    const literalMap = { 'me-chat': { method: 'POST' } }
    assert.equal(literalMap['toString'] === undefined, false, 'premise: literal inherits toString')
    assert.equal(literalMap['toString'].method, 'POST', 'premise: method check would pass')

    for (const request of requests) {
      results.push((await handler.fetch(request)).status)
    }
  } finally {
    delete Object.prototype.method
  }

  assert.deepEqual(
    results,
    inheritedKeys.map(() => 400),
    `inherited keys must be rejected even when the method check passes; got ${results}`,
  )
  assert.equal(calls.length, 0, 'no inherited-key request may reach the backend')

  // Confirm the pollution was cleaned up so later tests are unaffected.
  assert.equal({}.method, undefined)
})

// ── me-career-confirm ───────────────────────────────────────────────────────

test('me-career-confirm forwards a POST body with Authorization and the secret', async () => {
  const calls = []
  const handler = createProxyHandler({
    env: ME_ENV,
    fetchImpl: async (url, options) => {
      calls.push({ url: url.toString(), options })
      return Response.json({ status: 'ok', total_confirmed: 4 }, { status: 200 })
    },
  })

  const payload = JSON.stringify({ certifications: ['some-id'] })
  const response = await handler.fetch(
    new Request('https://gradusiq.example/api/proxy?target=me-career-confirm', {
      method: 'POST',
      headers: { Authorization: 'Bearer real-session-jwt', 'Content-Type': 'application/json' },
      body: payload,
    }),
  )

  assert.equal(response.status, 200)
  assert.equal(calls.length, 1)
  assert.equal(calls[0].url, 'https://backend.example/api/v2/student/me/career/confirm')
  assert.equal(calls[0].options.method, 'POST')
  assert.equal(calls[0].options.headers.Authorization, 'Bearer real-session-jwt')
  assert.equal(calls[0].options.headers['X-GradusIQ-Proxy-Secret'], 'server-only-secret')
  // JSON target: body stays a string, not an ArrayBuffer.
  assert.equal(typeof calls[0].options.body, 'string')
  assert.equal(calls[0].options.body, payload)
  assert.equal(calls[0].options.headers['Content-Type'], 'application/json')
})

test('me-career-confirm works with no body and is POST-only', async () => {
  const calls = []
  const handler = createProxyHandler({
    env: ME_ENV,
    fetchImpl: async (url, options) => {
      calls.push(options)
      return Response.json({ status: 'ok' }, { status: 200 })
    },
  })

  // The common case: confirm everything, no body at all.
  const ok = await handler.fetch(
    new Request('https://gradusiq.example/api/proxy?target=me-career-confirm', {
      method: 'POST',
      headers: { Authorization: 'Bearer t' },
    }),
  )
  assert.equal(ok.status, 200)
  assert.equal(calls[0].body, undefined)

  // GET against this target is a method mismatch.
  const asGet = await handler.fetch(
    new Request('https://gradusiq.example/api/proxy?target=me-career-confirm', { method: 'GET' }),
  )
  assert.equal(asGet.status, 400)
  assert.equal(calls.length, 1, 'the rejected GET must not have been forwarded')
})

// ── me-career-review / me-career-review-edit ────────────────────────────────

const REVIEW_URL = 'https://gradusiq.example/api/proxy?target=me-career-review'
const VALID_ID = '8f14e45f-ceea-467a-9f0e-1c2d3e4f5a6b'

function editUrl(table, id) {
  return (
    'https://gradusiq.example/api/proxy?target=me-career-review-edit' +
    `&table=${encodeURIComponent(table)}&id=${encodeURIComponent(id)}`
  )
}

test('me-career-review forwards a GET with Authorization and the secret', async () => {
  const calls = []
  const handler = createProxyHandler({
    env: ME_ENV,
    fetchImpl: async (url, options) => {
      calls.push({ url: url.toString(), options })
      return Response.json({ certifications: [] }, { status: 200 })
    },
  })

  const response = await handler.fetch(
    new Request(REVIEW_URL, { method: 'GET', headers: { Authorization: 'Bearer jwt' } }),
  )

  assert.equal(response.status, 200)
  assert.equal(calls[0].url, 'https://backend.example/api/v2/student/me/career/review')
  assert.equal(calls[0].options.method, 'GET')
  assert.equal(calls[0].options.headers.Authorization, 'Bearer jwt')
  assert.equal(calls[0].options.headers['X-GradusIQ-Proxy-Secret'], 'server-only-secret')
  assert.equal(calls[0].options.body, undefined)
})

test('me-career-review-edit builds the {table}/{id} path from validated query params', async () => {
  const calls = []
  const handler = createProxyHandler({
    env: ME_ENV,
    fetchImpl: async (url, options) => {
      calls.push({ url: url.toString(), options })
      return Response.json({ id: VALID_ID }, { status: 200 })
    },
  })

  const payload = JSON.stringify({ issuer: 'Amazon' })
  const response = await handler.fetch(
    new Request(editUrl('certifications', VALID_ID), {
      method: 'PATCH',
      headers: { Authorization: 'Bearer jwt', 'Content-Type': 'application/json' },
      body: payload,
    }),
  )

  assert.equal(response.status, 200)
  assert.equal(
    calls[0].url,
    `https://backend.example/api/v2/student/me/career/review/certifications/${VALID_ID}`,
  )
  assert.equal(calls[0].options.method, 'PATCH')
  // A PATCH body is JSON and must still be forwarded as text, not bytes.
  assert.equal(typeof calls[0].options.body, 'string')
  assert.equal(calls[0].options.body, payload)
  assert.equal(calls[0].options.headers.Authorization, 'Bearer jwt')
})

test('me-career-review-edit rejects an unknown table before forwarding', async () => {
  let forwarded = false
  const handler = createProxyHandler({
    env: ME_ENV,
    fetchImpl: async () => {
      forwarded = true
      return new Response()
    },
  })

  const rejected = [
    'students',
    'career_profiles', // the real table name is NOT a valid segment
    'institutions',
    'course_records',
    '__proto__',
    'CERTIFICATIONS',
    '',
    '../../students',
  ]

  for (const table of rejected) {
    const response = await handler.fetch(
      new Request(editUrl(table, VALID_ID), { method: 'PATCH', body: '{}' }),
    )
    assert.equal(response.status, 400, `table=${table} should be rejected`)
  }

  assert.equal(forwarded, false, 'no unknown table may reach the backend')
})

test('me-career-review-edit rejects a malformed record id', async () => {
  let forwarded = false
  const handler = createProxyHandler({
    env: ME_ENV,
    fetchImpl: async () => {
      forwarded = true
      return new Response()
    },
  })

  const badIds = ['', 'abc', '1', '../../secret', `${VALID_ID}x`, 'not-a-uuid-at-all']

  for (const id of badIds) {
    const response = await handler.fetch(
      new Request(editUrl('certifications', id), { method: 'PATCH', body: '{}' }),
    )
    assert.equal(response.status, 400, `id=${id} should be rejected`)
  }

  assert.equal(forwarded, false)
})

test('PATCH is confined to the review-edit target and never reaches the slug surface', async () => {
  let forwarded = false
  const handler = createProxyHandler({
    env: ME_ENV,
    fetchImpl: async () => {
      forwarded = true
      return new Response()
    },
  })

  // A PATCH naming a slug-addressed AI feature must not be routed anywhere.
  const slugPatch = await handler.fetch(
    new Request('https://gradusiq.example/api/proxy?student=jordanReyes&feature=gap', {
      method: 'PATCH',
      body: '{}',
    }),
  )
  assert.equal(slugPatch.status, 400)

  // PATCH against a GET-only me target is still a method mismatch.
  const wrongMethod = await handler.fetch(
    new Request(REVIEW_URL, { method: 'PATCH', body: '{}' }),
  )
  assert.equal(wrongMethod.status, 400)

  // And GET against the PATCH-only edit target likewise.
  const wrongMethod2 = await handler.fetch(
    new Request(editUrl('certifications', VALID_ID), { method: 'GET' }),
  )
  assert.equal(wrongMethod2.status, 400)

  assert.equal(forwarded, false)
})

test('genuinely unsupported methods are still 405', async () => {
  const handler = createProxyHandler({ env: ME_ENV, fetchImpl: async () => new Response() })

  // DELETE left this list when the planned-course removal target was added --
  // it is now a method the proxy carries, so it passes the 405 gate and is
  // rejected further down by the target's own method check. The case below
  // pins that it is still refused on a target that does not declare it.
  for (const method of ['PUT', 'HEAD', 'OPTIONS']) {
    const response = await handler.fetch(new Request(REVIEW_URL, { method }))
    assert.equal(response.status, 405, `${method} should be 405`)
  }

  let forwarded = false
  const strict = createProxyHandler({
    env: ME_ENV,
    fetchImpl: async () => {
      forwarded = true
      return new Response()
    },
  })
  const response = await strict.fetch(new Request(REVIEW_URL, { method: 'DELETE' }))
  assert.equal(response.status, 400, 'DELETE on a non-DELETE target should be 400')
  assert.equal(forwarded, false)
})

test('me targets reject wrong method, unknown target, and bad feature', async () => {
  let forwarded = false
  const handler = createProxyHandler({
    env: ME_ENV,
    fetchImpl: async () => {
      forwarded = true
      return new Response()
    },
  })

  // me-profile is GET-only.
  const wrongMethod = await handler.fetch(
    new Request('https://gradusiq.example/api/proxy?target=me-profile', { method: 'POST' }),
  )
  // Unknown target.
  const unknownTarget = await handler.fetch(
    new Request('https://gradusiq.example/api/proxy?target=me-danger', { method: 'POST' }),
  )
  // me-analyze with a feature outside the vocabulary.
  const badFeature = await handler.fetch(
    new Request('https://gradusiq.example/api/proxy?target=me-analyze&feature=nope', {
      method: 'POST',
    }),
  )

  assert.equal(wrongMethod.status, 400)
  assert.equal(unknownTarget.status, 400)
  assert.equal(badFeature.status, 400)
  assert.equal(forwarded, false)
})

// ── term-organized Academic Record targets ──────────────────────────────────

const PLANNING_ENV = {
  GRADUSIQ_BACKEND_URL: 'https://backend.example',
  GRADUSIQ_PROXY_SECRET: 'proxy-secret',
}

function planningHandler() {
  const seen = []
  const handler = createProxyHandler({
    env: PLANNING_ENV,
    fetchImpl: async (url, init) => {
      seen.push({ url: url.toString(), method: init.method, headers: init.headers })
      return new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } })
    },
  })
  return { handler, seen }
}

test('me-terms forwards a GET with Authorization and the proxy secret', async () => {
  const { handler, seen } = planningHandler()
  const response = await handler.fetch(
    new Request('https://gradusiq.example/api/proxy?target=me-terms', {
      method: 'GET',
      headers: { Authorization: 'Bearer token-abc' },
    }),
  )

  assert.equal(response.status, 200)
  assert.equal(seen[0].url, 'https://backend.example/api/v2/student/me/terms')
  assert.equal(seen[0].headers.Authorization, 'Bearer token-abc')
  assert.equal(seen[0].headers['X-GradusIQ-Proxy-Secret'], 'proxy-secret')
})

test('me-planned-courses accepts both GET and POST on one path', async () => {
  // Listing and adding share a URL, and a Vercel rewrite cannot route on
  // method -- so this target declares `methods`, and both must pass.
  for (const method of ['GET', 'POST']) {
    const { handler, seen } = planningHandler()
    const response = await handler.fetch(
      new Request('https://gradusiq.example/api/proxy?target=me-planned-courses', {
        method,
        headers: { Authorization: 'Bearer t' },
        ...(method === 'POST' ? { body: '{"course_code":"CSCE 121"}' } : {}),
      }),
    )
    assert.equal(response.status, 200)
    assert.equal(seen[0].url, 'https://backend.example/api/v2/student/me/planned-courses')
    assert.equal(seen[0].method, method)
  }
})

test('me-planned-courses rejects a method outside its methods array', async () => {
  const { handler, seen } = planningHandler()
  const response = await handler.fetch(
    new Request('https://gradusiq.example/api/proxy?target=me-planned-courses', {
      method: 'PATCH',
    }),
  )
  assert.equal(response.status, 400)
  assert.equal(seen.length, 0)
})

test('me-planned-courses forwards a valid term_id and rejects a malformed one', async () => {
  const uuid = '11111111-2222-3333-4444-555555555555'
  const { handler, seen } = planningHandler()
  await handler.fetch(
    new Request(`https://gradusiq.example/api/proxy?target=me-planned-courses&term_id=${uuid}`, {
      method: 'GET',
    }),
  )
  assert.equal(
    seen[0].url,
    `https://backend.example/api/v2/student/me/planned-courses?term_id=${uuid}`,
  )

  const { handler: bad, seen: badSeen } = planningHandler()
  const response = await bad.fetch(
    new Request(
      'https://gradusiq.example/api/proxy?target=me-planned-courses&term_id=' +
        encodeURIComponent('../../secret'),
      { method: 'GET' },
    ),
  )
  assert.equal(response.status, 400)
  assert.equal(badSeen.length, 0)
})

test('me-planned-course-remove is DELETE-only and requires a UUID', async () => {
  const uuid = '11111111-2222-3333-4444-555555555555'
  const { handler, seen } = planningHandler()
  await handler.fetch(
    new Request(`https://gradusiq.example/api/proxy?target=me-planned-course-remove&id=${uuid}`, {
      method: 'DELETE',
    }),
  )
  assert.equal(seen[0].url, `https://backend.example/api/v2/student/me/planned-courses/${uuid}`)
  assert.equal(seen[0].method, 'DELETE')

  for (const [method, id] of [['GET', uuid], ['DELETE', 'not-a-uuid'], ['DELETE', '']]) {
    const { handler: bad, seen: badSeen } = planningHandler()
    const response = await bad.fetch(
      new Request(
        `https://gradusiq.example/api/proxy?target=me-planned-course-remove&id=${encodeURIComponent(id)}`,
        { method },
      ),
    )
    assert.equal(response.status, 400)
    assert.equal(badSeen.length, 0)
  }
})

test('me-catalog-search forwards an encoded query and rejects junk', async () => {
  const { handler, seen } = planningHandler()
  await handler.fetch(
    new Request(
      'https://gradusiq.example/api/proxy?target=me-catalog-search&q=' +
        encodeURIComponent('MATH 251'),
      { method: 'GET' },
    ),
  )
  assert.equal(
    seen[0].url,
    'https://backend.example/api/v2/student/me/catalog/search?q=MATH%20251',
  )

  const rejected = ['', '<script>', 'a'.repeat(65), 'drop%00table']
  for (const query of rejected) {
    const { handler: bad, seen: badSeen } = planningHandler()
    const response = await bad.fetch(
      new Request(
        `https://gradusiq.example/api/proxy?target=me-catalog-search&q=${encodeURIComponent(query)}`,
        { method: 'GET' },
      ),
    )
    assert.equal(response.status, 400, `expected ${JSON.stringify(query)} to be rejected`)
    assert.equal(badSeen.length, 0)
  }
})

test('the planning targets do not forward Authorization on the slug branch', async () => {
  // The me-target/slug distinction must survive the new entries: a slug
  // request still forwards no inbound credential.
  const { handler, seen } = planningHandler()
  await handler.fetch(
    new Request('https://gradusiq.example/api/proxy?student=jordanReyes&feature=profile', {
      method: 'GET',
      headers: { Authorization: 'Bearer leaked' },
    }),
  )
  assert.equal(seen[0].headers.Authorization, undefined)
})

test('the target allowlist stays closed after adding the planning targets', async () => {
  const { handler, seen } = planningHandler()
  for (const target of ['me-planned', 'planned-courses', 'me-terms-x', 'constructor', '__proto__']) {
    const response = await handler.fetch(
      new Request(`https://gradusiq.example/api/proxy?target=${encodeURIComponent(target)}`, {
        method: 'GET',
      }),
    )
    assert.equal(response.status, 400, `expected ${target} to be rejected`)
  }
  assert.equal(seen.length, 0)
})
