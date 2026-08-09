// Two routing schemes share this function.
//
//   SLUG-ADDRESSED (?student=<slug>&feature=<feature>)
//     Forwards to /api/students/<slug>/... . These serve the demo fixtures.
//     The browser sends no credential and none is forwarded -- the backend
//     identifies the student from the slug alone.
//
//   SESSION-SCOPED (?target=me-analyze&feature=<feature> | ?target=me-chat
//                   | ?target=me-profile | ?target=me-resume-upload)
//     Forwards to /api/v2/student/me/... . These serve real students, whose
//     identity comes from a Supabase session JWT, so the inbound Authorization
//     header MUST be forwarded for the backend to resolve them via RLS.
//     me-resume-upload additionally carries a binary multipart body -- see the
//     `binary` flag on ME_TARGETS and the body branch in the handler.
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
const PROXY_SECRET_HEADER = 'X-GradusIQ-Proxy-Secret'

// Session-scoped targets. `feature` is required only by me-analyze, and is
// validated against the same analysis vocabulary the slug routes accept.
//
// `binary: true` marks a target whose body must NOT be read as text. Branching
// on an explicit target rather than sniffing Content-Type is deliberate:
// ME_TARGETS is already a closed allowlist, so the binary path is reachable
// only from a route we named, and a forged/absent Content-Type cannot flip an
// existing JSON target onto the binary branch.
//
// PROTOTYPE-LESS ON PURPOSE. As a plain object literal this map answers lookups
// for inherited keys -- ME_TARGETS['toString'] and ME_TARGETS['constructor']
// both return truthy values that were never allowlisted. The `method !==
// spec.method` check below happens to reject them today only because
// spec.method is undefined; if anything in the process pollutes
// Object.prototype.method, that accident stops holding and an unvalidated
// target reaches meBackendPath -- forwarded with the caller's bearer token and
// the proxy secret attached. Object.create(null) removes the inheritance
// entirely, so the allowlist is closed by construction rather than by a
// coincidence in an adjacent check. Object.assign keeps the entries readable.
const ME_TARGETS = Object.assign(Object.create(null), {
  'me-analyze': { method: 'POST', needsFeature: true },
  'me-chat': { method: 'POST', needsFeature: false },
  'me-profile': { method: 'GET', needsFeature: false },
  'me-resume-upload': { method: 'POST', needsFeature: false, binary: true },
  'me-career-confirm': { method: 'POST', needsFeature: false },
  'me-career-review': { method: 'GET', needsFeature: false },
  // `needsRecord` marks the one target whose backend path is not fixed: it
  // carries {table}/{id} path segments. Rather than let a caller hand the
  // proxy a path fragment, the two pieces arrive as separate query params and
  // are each validated against a closed allowlist / a UUID shape below, then
  // re-encoded into the path. The backend validates `table` against the same
  // allowlist independently -- the double check mirrors how ALLOWED_FEATURES
  // is already enforced in both places.
  'me-career-review-edit': { method: 'PATCH', needsFeature: false, needsRecord: true },
})
const ME_ANALYZE_FEATURES = new Set(['gap', 'fit', 'shift', 'professor-comments'])

// Must stay in step with TABLE_BY_SEGMENT in GradusIQ_career/resume/review.py.
const REVIEW_TABLES = new Set([
  'career_profile',
  'certifications',
  'work_experience',
  'projects',
])
const RECORD_ID_PATTERN =
  /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/

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

function meBackendPath(target, feature, reviewTable, recordId) {
  if (target === 'me-chat') return '/api/v2/student/me/chat'
  if (target === 'me-profile') return '/api/v2/student/me/profile'
  if (target === 'me-resume-upload') return '/api/v2/student/me/resume/upload'
  if (target === 'me-career-confirm') return '/api/v2/student/me/career/confirm'
  if (target === 'me-career-review') return '/api/v2/student/me/career/review'
  if (target === 'me-career-review-edit') {
    return `/api/v2/student/me/career/review/${encodeURIComponent(reviewTable)}/${encodeURIComponent(recordId)}`
  }
  return `/api/v2/student/me/analyze/${encodeURIComponent(feature)}`
}

export function createProxyHandler({ env = process.env, fetchImpl = globalThis.fetch } = {}) {
  return {
    async fetch(request) {
      const method = request.method
      if (method !== 'POST' && method !== 'GET' && method !== 'PATCH') {
        return jsonError(405, 'Method not allowed.')
      }

      const requestUrl = new URL(request.url)
      const target = requestUrl.searchParams.get('target') ?? ''
      const student = requestUrl.searchParams.get('student') ?? ''
      const feature = requestUrl.searchParams.get('feature') ?? ''
      const reviewTable = requestUrl.searchParams.get('table') ?? ''
      const recordId = requestUrl.searchParams.get('id') ?? ''

      const isMeTarget = target !== ''
      let path
      let isBinaryTarget = false

      if (isMeTarget) {
        const spec = ME_TARGETS[target]
        if (!spec || method !== spec.method) {
          return jsonError(400, 'Invalid analysis route.')
        }
        if (spec.needsFeature && !ME_ANALYZE_FEATURES.has(feature)) {
          return jsonError(400, 'Invalid analysis route.')
        }
        if (spec.needsRecord && (!REVIEW_TABLES.has(reviewTable) || !RECORD_ID_PATTERN.test(recordId))) {
          return jsonError(400, 'Invalid analysis route.')
        }
        isBinaryTarget = spec.binary === true
        path = meBackendPath(target, feature, reviewTable, recordId)
      } else {
        // PATCH exists only for the session-scoped review edit above. The
        // slug-addressed surface stays GET/POST-only: without this guard a
        // PATCH would fall through to the ALLOWED_FEATURES branch below and
        // could reach an AI route.
        if (method !== 'GET' && method !== 'POST') {
          return jsonError(400, 'Invalid analysis route.')
        }
        // Method and feature must agree: a GET may only reach a read route, and
        // a POST may only reach an AI route. This stops a GET from triggering
        // billable work and keeps the read route out of the POST-only surface.
        const allowed = method === 'GET' ? GET_FEATURES : ALLOWED_FEATURES
        if (!STUDENT_SLUG_PATTERN.test(student) || !allowed.has(feature)) {
          return jsonError(400, 'Invalid analysis route.')
        }
        path = backendPath(student, feature)
      }

      const backendUrl = backendBaseUrl(env.GRADUSIQ_BACKEND_URL ?? '')
      const proxySecret = (env.GRADUSIQ_PROXY_SECRET ?? '').trim()
      if (!backendUrl || !proxySecret) {
        return jsonError(503, 'Analysis proxy is not configured.')
      }

      const target_url = new URL(path, backendUrl)

      // Forward the request body. Analyze routes send none (path params only);
      // chat carries { message, history } in the body, so it must pass through.
      // A GET has no body to read or forward.
      //
      // BINARY TARGETS take a separate path. request.text() decodes the body as
      // UTF-8, which silently replaces every byte sequence that is not valid
      // UTF-8 with U+FFFD -- it does not throw, it corrupts. That is fine for
      // JSON and fatal for a PDF or DOCX, so file uploads are read as raw bytes
      // via arrayBuffer() and forwarded untouched.
      const headers = {
        Accept: 'application/json',
        [PROXY_SECRET_HEADER]: proxySecret,
      }

      let body
      if (isBinaryTarget) {
        const buffer = await request.arrayBuffer()
        body = buffer.byteLength ? buffer : undefined
        // Preserve the inbound Content-Type verbatim: multipart is unparseable
        // without its boundary parameter, so this must never be defaulted or
        // rewritten. When the caller sent none, forward none rather than
        // inventing application/json and mislabelling a file as JSON.
        const inboundContentType = request.headers.get('content-type')
        if (inboundContentType) headers['Content-Type'] = inboundContentType
      } else {
        const bodyText = method === 'GET' ? '' : await request.text()
        body = bodyText.length ? bodyText : undefined
        headers['Content-Type'] = request.headers.get('content-type') ?? 'application/json'
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
          body,
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
