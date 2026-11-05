import { QueryClient } from '@tanstack/react-query'
import { describe, expect, it, vi } from 'vitest'

import {
  clearCustomerSession,
  customerNotificationsQueryKey,
  customerSessionQueryKey,
  refreshCustomerSession,
  type CustomerSession,
} from './customerSession'

const customer: CustomerSession = {
  id: 'customer-1',
  mobile: '+919876543210',
  email: 'customer@example.test',
  mobile_verified: false,
  status: 'active',
  first_name: 'Test',
  last_name: 'Customer',
}

describe('customer session cache', () => {
  it('loads the shared session from the backend current-session endpoint', async () => {
    const queryClient = new QueryClient()
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(customer), { status: 200 }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await refreshCustomerSession(queryClient)

    expect(queryClient.getQueryData(customerSessionQueryKey)).toEqual(customer)
    expect(fetchMock).toHaveBeenCalledOnce()
    expect(String(fetchMock.mock.calls[0][0])).toContain('/api/v1/auth/me')
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ credentials: 'include' })
    vi.unstubAllGlobals()
    queryClient.clear()
  })

  it('does not retain an old customer when the server session cannot be verified', async () => {
    const queryClient = new QueryClient()
    queryClient.setQueryData(customerSessionQueryKey, customer)
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Session expired.' }), { status: 401 }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await expect(refreshCustomerSession(queryClient)).rejects.toThrow('Session expired.')

    expect(queryClient.getQueryData(customerSessionQueryKey)).toBeNull()
    vi.unstubAllGlobals()
    queryClient.clear()
  })

  it('clears user-specific notification cache when the verified account changes', async () => {
    const queryClient = new QueryClient()
    queryClient.setQueryData(customerSessionQueryKey, customer)
    queryClient.setQueryData([...customerNotificationsQueryKey, customer.id], { unread_count: 7 })
    const secondCustomer = { ...customer, id: 'customer-2' }
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(JSON.stringify(secondCustomer), { status: 200 })),
    )

    await refreshCustomerSession(queryClient)

    expect(queryClient.getQueryData(customerSessionQueryKey)).toEqual(secondCustomer)
    expect(queryClient.getQueryData([...customerNotificationsQueryKey, customer.id])).toBeUndefined()
    vi.unstubAllGlobals()
    queryClient.clear()
  })

  it('clears customer data after logout', () => {
    const queryClient = new QueryClient()
    queryClient.setQueryData(customerSessionQueryKey, customer)

    clearCustomerSession(queryClient)

    expect(queryClient.getQueryData(customerSessionQueryKey)).toBeNull()
    queryClient.clear()
  })
})
