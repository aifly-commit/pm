// 统一 API 客户端：自动携带 JWT，401 踢回登录页
const BASE = '/api/v1'

export function getToken() {
  return localStorage.getItem('pm_token') || ''
}

export function setToken(token) {
  localStorage.setItem('pm_token', token)
}

export function clearToken() {
  localStorage.removeItem('pm_token')
  localStorage.removeItem('pm_user')
}

export function getStoredUser() {
  try {
    return JSON.parse(localStorage.getItem('pm_user') || 'null')
  } catch {
    return null
  }
}

async function request(method, path, body) {
  const headers = { 'Content-Type': 'application/json' }
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (res.status === 401) {
    clearToken()
    if (location.pathname !== '/login') location.href = '/login'
    throw new Error('登录已过期，请重新登录')
  }
  let data = null
  try {
    data = await res.json()
  } catch {
    data = null
  }
  if (!res.ok) {
    const detail = data && data.detail
    const msg = Array.isArray(detail)
      ? detail.map((d) => d.msg || JSON.stringify(d)).join('；')
      : typeof detail === 'string'
        ? detail
        : `请求失败（${res.status}）`
    const err = new Error(msg)
    err.status = res.status
    throw err
  }
  return data
}

export const api = {
  get: (path) => request('GET', path),
  post: (path, body) => request('POST', path, body ?? {}),
  patch: (path, body) => request('PATCH', path, body),
  delete: (path) => request('DELETE', path),
}
