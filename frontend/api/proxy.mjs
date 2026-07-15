const ALLOWED_FEATURES = new Set(['gap', 'fit', 'shift', 'professor-comments', 'chat'])
const STUDENT_SLUG_PATTERN = /^[A-Za-z0-9]{1,64}$/
const PROXY_SECRET_HEADER = 'X-CampusIQ-Proxy-Secret'

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

// Chat forwards to /chat; analysis features forward to /analyze/{feature}.
function backendPath(student, feature) {
  const slug = encodeURIComponent(student)
  return feature === 'chat'
    ? `/api/students/${slug}/chat`
    : `/api/students/${slug}/analyze/${feature}`
}

export function createProxyHandler({ env = process.env, fetchImpl = globalThis.fetch } = {}) {
  return {
    async fetch(request) {
      if (request.method !== 'POST') return jsonError(405, 'Method not allowed.')

      const requestUrl = new URL(request.url)
      const student = requestUrl.searchParams.get('student') ?? ''
      const feature = requestUrl.searchParams.get('feature') ?? ''
      if (!STUDENT_SLUG_PATTERN.test(student) || !ALLOWED_FEATURES.has(feature)) {
        return jsonError(400, 'Invalid analysis route.')
      }

      const backendUrl = backendBaseUrl(env.CAMPUSIQ_BACKEND_URL ?? '')
      const proxySecret = (env.CAMPUSIQ_PROXY_SECRET ?? '').trim()
      if (!backendUrl || !proxySecret) {
        return jsonError(503, 'Analysis proxy is not configured.')
      }

      const target = new URL(backendPath(student, feature), backendUrl)

      // Forward the request body. Analyze routes send none (path params only);
      // chat carries { message, history } in the body, so it must pass through.
      const contentType = request.headers.get('content-type') ?? 'application/json'
      const bodyText = await request.text()

      try {
        const backendResponse = await fetchImpl(target, {
          method: 'POST',
          headers: {
            Accept: 'application/json',
            'Content-Type': contentType,
            [PROXY_SECRET_HEADER]: proxySecret,
          },
          body: bodyText.length ? bodyText : undefined,
        })
        const headers = new Headers()
        const respContentType = backendResponse.headers.get('content-type')
        if (respContentType) headers.set('content-type', respContentType)
        return new Response(await backendResponse.arrayBuffer(), {
          status: backendResponse.status,
          headers,
        })
      } catch {
        return jsonError(502, 'Analysis backend is unavailable.')
      }
    },
  }
}

export default createProxyHandler()
