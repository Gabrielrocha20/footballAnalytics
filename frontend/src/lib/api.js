const TOKEN_KEY = 'tradefot-token'

let unauthorizedHandler = null
export function onUnauthorized(handler) {
  unauthorizedHandler = handler
}

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}
export function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.status = status
  }
}

async function request(path, options = {}) {
  const token = getToken()
  const response = await fetch(path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
  })
  if (response.status === 204) return null
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    if (response.status === 401 && unauthorizedHandler) unauthorizedHandler()
    throw new ApiError(payload.detail || payload.message || `Erro HTTP ${response.status}`, response.status)
  }
  return payload
}

function query(params = {}) {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') search.set(key, value)
  })
  const string = search.toString()
  return string ? `?${string}` : ''
}

export const api = {
  // auth
  authStatus: () => request('/api/auth/status'),
  authMe: () => request('/api/auth/me'),
  login: (token) => request('/api/auth/login', { method: 'POST', body: JSON.stringify({ token }) }),
  logout: () => request('/api/auth/logout', { method: 'POST' }),

  // data
  sources: () => request('/api/sources'),
  leagues: (source, search = '') => request(`/api/leagues${query({ source, search })}`),
  upcoming: (params) => request(`/api/matches/upcoming${query(params)}`),
  league: (source, leagueId, season) =>
    request(`/api/leagues/${encodeURIComponent(leagueId)}${query({ source, season })}`),
  analysis: (source, matchId) =>
    request(`/api/matches/${matchId}/analysis${query({ source })}`),
  performance: (source, days = 7, limit = 30) =>
    request(`/api/performance${query({ source, days, limit })}`),
  neuralPrediction: (source, matchId) =>
    request(`/api/matches/${matchId}/prediction${query({ source })}`),
  modelStatus: (source) => request(`/api/models/status${query({ source })}`),
  trainModel: (source, force = false) =>
    request('/api/models/train', { method: 'POST', body: JSON.stringify({ source, force }) }),

  // background jobs
  sync: (source, scope) =>
    request('/api/sync', { method: 'POST', body: JSON.stringify({ source, scope }) }),
  minutes: (source, matchIds) =>
    request('/api/minutes', { method: 'POST', body: JSON.stringify({ source, match_ids: matchIds }) }),
  job: (jobId) => request(`/api/jobs/${jobId}`),
}

export { ApiError }
