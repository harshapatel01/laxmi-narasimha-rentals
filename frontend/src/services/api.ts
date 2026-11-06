import { apiErrorMessage, csrfTokenForRequest, updateCsrfTokenFromResponse } from './requestUtils'

export interface ApiHealth {
  status: string
  service: string
}

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
const apiV1BaseUrl = new URL('/api/v1/', apiBaseUrl)

export async function getApiHealth(): Promise<ApiHealth> {
  const response = await fetch(new URL('/health', apiBaseUrl))
  if (!response.ok) {
    throw new Error(`API health check failed with status ${response.status}`)
  }
  return response.json() as Promise<ApiHealth>
}

export class ApiError extends Error {
  readonly status: number

  constructor(
    message: string,
    status: number,
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? 'GET').toUpperCase()
  const headers = new Headers(init.headers)
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  if (method !== 'GET') {
    const token = csrfTokenForRequest(path, document.cookie)
    if (token) headers.set('X-CSRF-Token', token)
  }
  const response = await fetch(new URL(path.replace(/^\//, ''), apiV1BaseUrl), {
    ...init,
    method,
    headers,
    credentials: 'include',
  })
  updateCsrfTokenFromResponse(path, response)
  const body: unknown = await response.json().catch(() => undefined)
  if (!response.ok) {
    throw new ApiError(apiErrorMessage(body, response.status), response.status)
  }
  return body as T
}

export function apiAssetUrl(path: string): string {
  return new URL(path, apiBaseUrl).toString()
}
