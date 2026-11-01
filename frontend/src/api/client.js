// Thin fetch wrapper. All API calls go through /api (nginx / vite proxy strips it).
const BASE = import.meta.env.VITE_API_URL || '/api'
const TOKEN_KEY = 'sfa_token'

export class ApiError extends Error {
  constructor(message, status, body) {
    super(message)
    this.status = status
    this.code = body?.code
    this.details = body?.details
    this.body = body
  }
}

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setToken(token) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* private mode: token lives only in memory for this tab */
  }
}

function buildUrl(path, query) {
  const url = new URL(BASE + path, window.location.origin)
  Object.entries(query || {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, v)
  })
  return url
}

function messageFrom(body, status) {
  const detail = body?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((d) => `${(d.loc || []).slice(-1)[0]}: ${d.msg}`).join('; ')
  if (status === 0) return 'The server could not be reached. Check that the backend is running.'
  return `Request failed (${status})`
}

async function request(path, { method = 'GET', json, form, query, raw = false, signal } = {}) {
  const headers = {}
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  let body
  if (json !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(json)
  } else if (form !== undefined) {
    body = form // FormData or URLSearchParams: browser sets the content type
  }
  let res
  try {
    res = await fetch(buildUrl(path, query), { method, headers, body, signal })
  } catch (err) {
    if (err.name === 'AbortError') throw err
    throw new ApiError(messageFrom(null, 0), 0, null)
  }
  if (res.status === 401 && token) window.dispatchEvent(new Event('sfa:unauthorized'))
  if (!res.ok) {
    let parsed = null
    try {
      parsed = await res.json()
    } catch {
      /* non-JSON error page */
    }
    throw new ApiError(messageFrom(parsed, res.status), res.status, parsed)
  }
  if (raw) return res
  if (res.status === 204) return null
  const type = res.headers.get('content-type') || ''
  return type.includes('application/json') ? res.json() : res.blob()
}

export const api = {
  get: (path, query, opts) => request(path, { query, ...opts }),
  post: (path, json, query) => request(path, { method: 'POST', json: json ?? {}, query }),
  put: (path, json) => request(path, { method: 'PUT', json }),
  del: (path, query) => request(path, { method: 'DELETE', query }),
  form: (path, formData, query) => request(path, { method: 'POST', form: formData, query }),
  raw: (path, query) => request(path, { query, raw: true }),
}

export async function downloadFile(path, query, fallbackName = 'download') {
  const res = await api.raw(path, query)
  const blob = await res.blob()
  const disposition = res.headers.get('content-disposition') || ''
  const match = disposition.match(/filename="?([^";]+)"?/)
  saveBlob(blob, match ? match[1] : fallbackName)
}

export function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 2000)
}

export function wsUrl(path) {
  const explicit = import.meta.env.VITE_WS_URL
  if (explicit) return explicit + path
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}${path}`
}
