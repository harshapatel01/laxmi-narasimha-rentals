import { describe, expect, it, vi } from 'vitest'

import { apiRequest } from './api'

describe('API request credentials', () => {
  it('includes credentials for admin login and session checks', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    )
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('document', { cookie: '' })

    await apiRequest('/admin/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username_or_email: 'admin', password: 'test-password' }),
    })
    await apiRequest('/admin/auth/me')

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ credentials: 'include' })
    expect(String(fetchMock.mock.calls[0][0])).toContain('/api/v1/admin/auth/login')
    expect(fetchMock.mock.calls[1][1]).toMatchObject({ credentials: 'include' })
    expect(String(fetchMock.mock.calls[1][0])).toContain('/api/v1/admin/auth/me')
    vi.unstubAllGlobals()
  })
})
