const ALLOWED_FEATURES = new Set(['gap', 'fit', 'shift', 'professor-comments'])
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

      const target = new URL(
        `/api/students/${encodeURIComponent(student)}/analyze/${feature}`,
        backendUrl,
      )

      try {
        const backendResponse = await fetchImpl(target, {
          method: 'POST',
          headers: {
            Accept: 'application/json',
            [PROXY_SECRET_HEADER]: proxySecret,
          },
        })
        const headers = new Headers()
        const contentType = backendResponse.headers.get('content-type')
        if (contentType) headers.set('content-type', contentType)
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
