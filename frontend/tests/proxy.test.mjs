import assert from 'node:assert/strict'
import test from 'node:test'

import { createProxyHandler } from '../api/proxy.mjs'

const REQUEST_URL = 'https://campusiq.example/api/proxy?student=jordanReyes&feature=gap'

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

  // Methods other than GET/POST are rejected outright.
  assert.equal(
    (await handler.fetch(new Request(REQUEST_URL, { method: 'PUT' }))).status,
    405,
  )
  assert.equal(
    (await handler.fetch(new Request(REQUEST_URL, { method: 'DELETE' }))).status,
    405,
  )
  // GET is now a valid method, but only for read features -- a GET naming an
  // AI feature is a method/feature mismatch (400), never a triggered AI call.
  assert.equal((await handler.fetch(new Request(REQUEST_URL))).status, 400)
  assert.equal(
    (
      await handler.fetch(
        new Request('https://campusiq.example/api/proxy?student=../secret&feature=gap', {
          method: 'POST',
        }),
      )
    ).status,
    400,
  )
  assert.equal(
    (
      await handler.fetch(
        new Request('https://campusiq.example/api/proxy?student=jordanReyes&feature=unknown', {
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
      CAMPUSIQ_BACKEND_URL: 'https://backend.example',
      CAMPUSIQ_PROXY_SECRET: 'server-only-secret',
    },
    fetchImpl: async (url, options) => {
      calls.push({ url: url.toString(), options })
      return Response.json({ status: 'success' }, { status: 200 })
    },
  })

  const response = await handler.fetch(
    new Request(REQUEST_URL, {
      method: 'POST',
      headers: { 'X-CampusIQ-Proxy-Secret': 'browser-supplied-value' },
    }),
  )

  assert.equal(response.status, 200)
  assert.equal(calls.length, 1)
  assert.equal(calls[0].url, 'https://backend.example/api/students/jordanReyes/analyze/gap')
  assert.equal(calls[0].options.headers['X-CampusIQ-Proxy-Secret'], 'server-only-secret')
  assert.equal(JSON.stringify(calls[0].options).includes('browser-supplied-value'), false)
})

test('server proxy preserves sanitized backend status and handles transport failure', async () => {
  const env = {
    CAMPUSIQ_BACKEND_URL: 'https://backend.example',
    CAMPUSIQ_PROXY_SECRET: 'server-only-secret',
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

const PROFILE_URL = 'https://campusiq.example/api/proxy?student=jordanReyes&feature=profile'

test('server proxy forwards GET profile to the backend profile route with its secret', async () => {
  const calls = []
  const handler = createProxyHandler({
    env: {
      CAMPUSIQ_BACKEND_URL: 'https://backend.example',
      CAMPUSIQ_PROXY_SECRET: 'server-only-secret',
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
  assert.equal(calls[0].options.headers['X-CampusIQ-Proxy-Secret'], 'server-only-secret')
  // A GET must not carry a forwarded body.
  assert.equal(calls[0].options.body, undefined)
})

test('server proxy rejects a POST to the read-only profile feature', async () => {
  let forwarded = false
  const handler = createProxyHandler({
    env: {
      CAMPUSIQ_BACKEND_URL: 'https://backend.example',
      CAMPUSIQ_PROXY_SECRET: 'server-only-secret',
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
      CAMPUSIQ_BACKEND_URL: 'https://backend.example',
      CAMPUSIQ_PROXY_SECRET: 'server-only-secret',
    },
    fetchImpl: async () => new Response(),
  })

  const response = await handler.fetch(
    new Request('https://campusiq.example/api/proxy?student=../secret&feature=profile', {
      method: 'GET',
    }),
  )

  assert.equal(response.status, 400)
})
