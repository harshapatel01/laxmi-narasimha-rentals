const csrfTokens: Partial<Record<'customer' | 'admin', string>> = {}

function csrfScopeForRequest(path: string): 'customer' | 'admin' {
  return path.replace(/^\//, '').startsWith('admin/') ? 'admin' : 'customer'
}

function csrfCookieForScope(scope: 'customer' | 'admin'): string {
  return scope === 'admin' ? 'lnr_admin_csrf' : 'lnr_customer_csrf'
}

export function csrfTokenForRequest(
  path: string,
  cookieHeader = '',
): string | undefined {
  const scope = csrfScopeForRequest(path)
  const cachedToken = csrfTokens[scope]
  if (cachedToken) return cachedToken

  const cookieName = csrfCookieForScope(scope)
  const cookie = cookieHeader
    .split(';')
    .map((part) => part.trim())
    .find((part) => part.startsWith(`${cookieName}=`))
  if (!cookie) return undefined

  try {
    return decodeURIComponent(cookie.slice(cookie.indexOf('=') + 1))
  } catch {
    return undefined
  }
}

export function updateCsrfTokenFromResponse(path: string, response: Response): void {
  const scope = csrfScopeForRequest(path)
  const token = response.headers.get('X-CSRF-Token')
  if (response.ok && token) {
    csrfTokens[scope] = token
    return
  }

  const normalizedPath = path.replace(/^\//, '').split('?')[0]
  const sessionCheckPath = `${scope === 'admin' ? 'admin/' : ''}auth/me`
  const logoutPath = `${scope === 'admin' ? 'admin/' : ''}auth/logout`
  if (
    normalizedPath === sessionCheckPath
    || (normalizedPath === logoutPath && response.ok)
  ) {
    delete csrfTokens[scope]
  }
}

export function clearCsrfTokenForRequest(path: string): void {
  delete csrfTokens[csrfScopeForRequest(path)]
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

export function apiErrorMessage(body: unknown, status: number): string {
  if (isRecord(body) && typeof body.detail === 'string') {
    return body.detail
  }

  if (isRecord(body) && Array.isArray(body.detail)) {
    const errors = body.detail.flatMap((item) => {
      if (!isRecord(item) || typeof item.msg !== 'string') return []
      const location = Array.isArray(item.loc)
        ? item.loc.filter((part): part is string | number => typeof part === 'string' || typeof part === 'number')
        : []
      const field = location.filter((part) => part !== 'body').join('.')
      return [field ? `${field}: ${item.msg}` : item.msg]
    })
    if (errors.length > 0) return `Please correct the following: ${errors.join('; ')}`
  }

  return `Request failed (${status}).`
}
