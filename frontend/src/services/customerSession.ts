import { useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { ApiError, apiRequest } from './api'

export interface CustomerSession {
  id: string
  mobile: string
  email: string | null
  mobile_verified: boolean
  status: string
  first_name: string | null
  last_name: string | null
}

export const customerSessionQueryKey = ['customer-session'] as const
export const customerNotificationsQueryKey = ['customer-notifications'] as const

const SESSION_CHANNEL_NAME = 'lnr-customer-session'

function clearCustomerQueries(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.clear()
  queryClient.setQueryData(customerSessionQueryKey, null)
}

function clearPreviousCustomerData(
  queryClient: ReturnType<typeof useQueryClient>,
  customer: CustomerSession,
) {
  const previous = queryClient.getQueryData<CustomerSession | null>(customerSessionQueryKey)
  if (previous && previous.id !== customer.id) {
    queryClient.removeQueries({ queryKey: customerNotificationsQueryKey })
  }
}

function broadcastSessionChange(type: 'login' | 'logout') {
  if (typeof BroadcastChannel === 'undefined') return
  const channel = new BroadcastChannel(SESSION_CHANNEL_NAME)
  channel.postMessage({ type })
  channel.close()
}

export async function refreshCustomerSession(
  queryClient: ReturnType<typeof useQueryClient>,
): Promise<CustomerSession> {
  let customer: CustomerSession
  try {
    customer = await apiRequest<CustomerSession>('/auth/me')
  } catch (error) {
    queryClient.setQueryData(customerSessionQueryKey, null)
    queryClient.removeQueries({ queryKey: customerNotificationsQueryKey })
    broadcastSessionChange('login')
    throw error
  }
  clearPreviousCustomerData(queryClient, customer)
  queryClient.setQueryData(customerSessionQueryKey, customer)
  broadcastSessionChange('login')
  return customer
}

export function clearCustomerSession(
  queryClient: ReturnType<typeof useQueryClient>,
) {
  clearCustomerQueries(queryClient)
  broadcastSessionChange('logout')
}

export function useCustomerSession() {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: customerSessionQueryKey,
    queryFn: async (): Promise<CustomerSession | null> => {
      try {
        const customer = await apiRequest<CustomerSession>('/auth/me')
        clearPreviousCustomerData(queryClient, customer)
        return customer
      } catch (error) {
        if (error instanceof ApiError && [401, 403].includes(error.status)) return null
        throw error
      }
    },
    staleTime: 30_000,
    retry: false,
    refetchOnWindowFocus: true,
  })

  useEffect(() => {
    const channel = typeof BroadcastChannel === 'undefined'
      ? null
      : new BroadcastChannel(SESSION_CHANNEL_NAME)
    if (channel) {
      channel.onmessage = (event: MessageEvent<{ type?: string }>) => {
        if (event.data?.type === 'logout') {
          clearCustomerQueries(queryClient)
          return
        }
        if (event.data?.type === 'login') {
          void queryClient.resetQueries({ queryKey: customerSessionQueryKey, exact: true })
        }
      }
    }
    const onPageShow = (event: PageTransitionEvent) => {
      if (event.persisted) {
        void queryClient.resetQueries({ queryKey: customerSessionQueryKey, exact: true })
      }
    }
    window.addEventListener('pageshow', onPageShow)
    return () => {
      channel?.close()
      window.removeEventListener('pageshow', onPageShow)
    }
  }, [queryClient])

  if (query.isPending || (query.isFetching && query.data == null)) {
    return { status: 'loading' as const, customer: null }
  }
  if (query.isError) return { status: 'error' as const, customer: null }
  if (query.data) return { status: 'authenticated' as const, customer: query.data }
  return { status: 'anonymous' as const, customer: null }
}
