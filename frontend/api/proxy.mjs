// Two routing schemes share this function.
//
//   SLUG-ADDRESSED (?student=<slug>&feature=<feature>)
//     Forwards to /api/students/<slug>/... . These serve the demo fixtures.
//     The browser sends no credential and none is forwarded -- the backend
//     identifies the student from the slug alone.
//
//   SESSION-SCOPED (?target=me-analyze&feature=<feature> | ?target=me-chat
//                   | ?target=me-profile)
//     Forwards to /api/v2/student/me/... . These serve real students, whose
//     identity comes from a Supabase session JWT, so the inbound Authorization
//     header MUST be forwarded for the backend to resolve them via RLS.
//
// Authorization is forwarded for `target` requests ONLY -- see the single
// `if (isMeTarget)` block below, which is the one place that distinction is
// enforced. Slug-addressed requests continue to forward no inbound header of
// any kind, preserving the anti-spoofing property those routes rely on.
//
// The proxy secret is attached to every forwarded request either way.

// POST features run AI work; 'profile' is a plain read and is the only GET.
const ALLOWED_FEATURES = new Set(['gap', 'fit', 'shift', 'professor-comments', 'chat'])
const GET_FEATURES = new Set(['profile'])
const STUDENT_SLUG_PATTERN = /^[A-Za-z0-9]{1,64}$/
const PROXY_SECRET_HEADER = 'X-CampusIQ-Proxy-Secret'

// Session-scoped targets. `feature` is required only by me-analyze, and is
// validated against the same analysis vocabulary the slug routes accept.
const ME_TARGETS = {
  'me-analyze': { method: 'POST', needsFeature: true },
  'me-chat': { method: 'POST', needsFeature: false },
  'me-profile': { method: 'GET', needsFeature: false },
}
const ME_ANALYZE_FEATURES = new Set(['gap', 'fit', 'shift', 'professor-comments'])

function jsonError(status, detail) {
  return Response.json({ detail }, { status })
}

function backendBaseUrl(value) {
  try {
    const url = new URL(value)
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return null
    return url
  } catch {
    return null
  }
}

// Chat forwards to /chat, profile to /profile; analysis features to
// /analyze/{feature}.
function backendPath(student, feature) {
  const slug = encodeURIComponent(student)
  if (feature === 'chat') return `/api/students/${slug}/chat`
  if (feature === 'profile') return `/api/students/${slug}/profile`
  return `/api/students/${slug}/analyze/${feature}`
}

function meBackendPath(target, feature) {
  if (target === 'me-chat') return '/api/v2/student/me/chat'
  if (target === 'me-profile') return '/api/v2/student/me/profile'
  return `/api/v2/student/me/analyze/${encodeURIComponent(feature)}`
}

export function createProxyHandler({ env = process.env, fetchImpl = globalThis.fetch } = {}) {
  return {
    async fetch(request) {
      const method = request.method
      if (method !== 'POST' && method !== 'GET') {
        return jsonError(405, 'Method not allowed.')
      }

      const requestUrl = new URL(request.url)
      const target = requestUrl.searchParams.get('target') ?? ''
      const student = requestUrl.searchParams.get('student') ?? ''
      const feature = requestUrl.searchParams.get('feature') ?? ''

      const isMeTarget = target !== ''
      let path

      if (isMeTarget) {
        const spec = ME_TARGETS[target]
        if (!spec || method !== spec.method) {
          return jsonError(400, 'Invalid analysis route.')
        }
        if (spec.needsFeature && !ME_ANALYZE_FEATURES.has(feature)) {
          return jsonError(400, 'Invalid analysis route.')
        }
        path = meBackendPath(target, feature)
      } else {
        // Method and feature must agree: a GET may only reach a read route, and
        // a POST may only reach an AI route. This stops a GET from triggering
        // billable work and keeps the read route out of the POST-only surface.
        const allowed = method === 'GET' ? GET_FEATURES : ALLOWED_FEATURES
        if (!STUDENT_SLUG_PATTERN.test(student) || !allowed.has(feature)) {
          return jsonError(400, 'Invalid analysis route.')
        }
        path = backendPath(student, feature)
      }

      const backendUrl = backendBaseUrl(env.CAMPUSIQ_BACKEND_URL ?? '')
      const proxySecret = (env.CAMPUSIQ_PROXY_SECRET ?? '').trim()
      if (!backendUrl || !proxySecret) {
        return jsonError(503, 'Analysis proxy is not configured.')
      }

      const target_url = new URL(path, backendUrl)

      // Forward the request body. Analyze routes send none (path params only);
      // chat carries { message, history } in the body, so it must pass through.
      // A GET has no body to read or forward.
      const contentType = request.headers.get('content-type') ?? 'application/json'
      const bodyText = method === 'GET' ? '' : await request.text()

      const headers = {
        Accept: 'application/json',
        'Content-Type': contentType,
        [PROXY_SECRET_HEADER]: proxySecret,
      }

      // THE distinction: session-scoped targets forward the caller's bearer
      // token so the backend can resolve them through RLS. Slug-addressed
      // requests never do -- a browser-supplied Authorization header on those
      // is ignored, exactly as before.
      if (isMeTarget) {
        const authorization = request.headers.get('authorization')
        if (authorization) headers.Authorization = authorization
      }

      try {
        const backendResponse = await fetchImpl(target_url, {
          method,
          headers,
          body: bodyText.length ? bodyText : undefined,
        })
        const responseHeaders = new Headers()
        const respContentType = backendResponse.headers.get('content-type')
        if (respContentType) responseHeaders.set('content-type', respContentType)
        return new Response(await backendResponse.arrayBuffer(), {
          status: backendResponse.status,
          headers: responseHeaders,
        })
      } catch {
        return jsonError(502, 'Analysis backend is unavailable.')
      }
    },
  }
}

export default createProxyHandler()
