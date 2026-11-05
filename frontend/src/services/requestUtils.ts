export function csrfTokenForRequest(
  path: string,
  cookieHeader: string,
): string | undefined {
  const cookieName = path.replace(/^\//, '').startsWith('admin/')
    ? 'lnr_admin_csrf'
    : 'lnr_customer_csrf'
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
