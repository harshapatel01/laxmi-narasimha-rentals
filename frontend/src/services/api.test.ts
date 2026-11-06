import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'

import { apiRequest } from './api'
import { refreshCustomerSession } from './customerSession'
import { clearCsrfTokenForRequest } from './requestUtils'

describe('API request credentials and CSRF tokens', () => {
  it('captures admin CSRF tokens from login and session responses', async () => {
    clearCsrfTokenForRequest('/admin/auth/me')
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ mfa_required: false }), {
        status: 200,
        headers: { 'X-CSRF-Token': 'admin-csrf-token' },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: 'admin-1' }), {
        status: 200,
        headers: { 'X-CSRF-Token': 'admin-csrf-token' },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('document', { cookie: '' })

    await apiRequest('/admin/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username_or_email: 'admin', password: 'test-password' }),
    })
    await apiRequest('/admin/auth/me')
    await apiRequest('/admin/bookings', { method: 'POST', body: JSON.stringify({}) })

    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ credentials: 'include' })
    expect(String(fetchMock.mock.calls[0][0])).toContain('/api/v1/admin/auth/login')
    expect(fetchMock.mock.calls[1][1]).toMatchObject({ credentials: 'include' })
    expect(String(fetchMock.mock.calls[1][0])).toContain('/api/v1/admin/auth/me')
    expect(new Headers(fetchMock.mock.calls[2][1]?.headers).get('X-CSRF-Token')).toBe('admin-csrf-token')

    vi.unstubAllGlobals()
    clearCsrfTokenForRequest('/admin/auth/me')
  })

  it('restores a customer CSRF token after reload and sends it with booking POST', async () => {
    clearCsrfTokenForRequest('/auth/me')
    const queryClient = new QueryClient()
    const customer = {
      id: 'customer-1',
      mobile: '+919876543210',
      email: 'customer@example.test',
      mobile_verified: true,
      status: 'active',
      first_name: 'Test',
      last_name: 'Customer',
    }
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(customer), {
        status: 200,
        headers: { 'X-CSRF-Token': 'customer-csrf-token' },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: 'booking-1' }), {
        status: 201,
      }))
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('document', { cookie: '' })

    await refreshCustomerSession(queryClient)
    await apiRequest('/bookings', {
      method: 'POST',
      body: JSON.stringify({ vehicle_id: 'vehicle-1' }),
    })

    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(String(fetchMock.mock.calls[0][0])).toContain('/api/v1/auth/me')
    expect(String(fetchMock.mock.calls[1][0])).toContain('/api/v1/bookings')
    expect(fetchMock.mock.calls[1][1]).toMatchObject({ credentials: 'include' })
    expect(new Headers(fetchMock.mock.calls[1][1]?.headers).get('X-CSRF-Token')).toBe('customer-csrf-token')

    vi.unstubAllGlobals()
    clearCsrfTokenForRequest('/auth/me')
    queryClient.clear()
  })
})
