export function customerPostAuthDestination(
  next: string | null,
  origin = window.location.origin,
): string {
  if (!next || !next.startsWith('/') || next.startsWith('//') || next.includes('\\')) {
    return '/'
  }
  try {
    const destination = new URL(next, origin)
    if (destination.origin !== origin) return '/'
    if (destination.pathname === '/') return '/'
    if (destination.pathname === '/vehicles') return '/vehicles'
    if (/^\/vehicles\/[0-9a-f-]{36}\/book$/i.test(destination.pathname)) {
      return destination.pathname
    }
    if (
      destination.pathname === '/bookings'
      || destination.pathname === '/account'
      || destination.pathname === '/notifications'
    ) {
      return `${destination.pathname}${destination.search}${destination.hash}`
    }
    return '/'
  } catch {
    return '/'
  }
}

export async function runAfterSuccessfulCustomerRequest<T>(
  request: () => Promise<T>,
  onSuccess: (result: T) => void | Promise<void>,
): Promise<T> {
  const result = await request()
  await onSuccess(result)
  return result
}
