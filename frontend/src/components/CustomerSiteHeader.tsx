import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Bell, Menu, X } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'

import { ApiError, apiRequest } from '../services/api'
import {
  clearCustomerSession,
  customerNotificationsQueryKey,
  useCustomerSession,
} from '../services/customerSession'

function messageFor(error: unknown): string {
  return error instanceof Error
    ? error.message
    : 'The request could not be completed. Please try again.'
}

export function CustomerAccountNavigation({
  className = 'customer-header-action',
}: {
  className?: string
}) {
  const session = useCustomerSession()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [logoutError, setLogoutError] = useState('')
  const unreadNotifications = useQuery({
    queryKey: [...customerNotificationsQueryKey, session.customer?.id],
    queryFn: () => apiRequest<{ unread_count: number }>('/notifications/unread-count'),
    enabled: session.status === 'authenticated',
    retry: false,
  })

  useEffect(() => {
    const refreshCount = () => {
      void queryClient.invalidateQueries({ queryKey: customerNotificationsQueryKey })
    }
    window.addEventListener('lnr-notifications-updated', refreshCount)
    return () => window.removeEventListener('lnr-notifications-updated', refreshCount)
  }, [queryClient])

  async function logout() {
    setLogoutError('')
    try {
      await apiRequest('/auth/logout', { method: 'POST' })
      clearCustomerSession(queryClient)
      navigate('/', { replace: true })
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        clearCustomerSession(queryClient)
        navigate('/', { replace: true })
        return
      }
      setLogoutError(messageFor(error))
    }
  }

  const unreadCount = session.status === 'authenticated'
    ? unreadNotifications.data?.unread_count ?? 0
    : 0

  return (
    <>
      {session.status === 'authenticated' ? (
        <>
          <Link className={className} to="/bookings">My bookings</Link>
          <Link
            className={className}
            to="/notifications"
            aria-label={`Notifications${unreadCount > 0 ? `, ${unreadCount} unread` : ''}`}
            title={unreadNotifications.isError ? 'Notification count is temporarily unavailable.' : undefined}
          >
            <Bell size={15} /> Notifications{unreadCount > 0 ? ` (${unreadCount})` : ''}
          </Link>
          <Link className={className} to="/account">My account</Link>
          <button type="button" className={className} onClick={() => void logout()}>
            Logout
          </button>
        </>
      ) : session.status === 'loading' ? (
        <span className={className} role="status">Checking session…</span>
      ) : session.status === 'error' ? (
        <span className={className} role="status">Account unavailable</span>
      ) : (
        <>
          <Link className={className} to="/login">Customer sign in</Link>
          <Link className={className} to="/register">Create account</Link>
        </>
      )}
      {session.status === 'anonymous' && (
        <Link className={className} to="/admin/login">Admin</Link>
      )}
      {logoutError && <p className="vehicle-notice error" role="alert">{logoutError}</p>}
    </>
  )
}

export function CustomerSiteHeader() {
  const [menuOpen, setMenuOpen] = useState(false)

  return (
    <header className="public-vehicles-header">
      <Link className="brand" to="/" aria-label="Laxmi Narasimha Rentals home">
        <span className="brand-mark">LN</span>
        <span className="brand-name"><strong>LAXMI NARASIMHA</strong><small>RENTALS</small></span>
      </Link>
      <button
        className="customer-nav-toggle"
        type="button"
        aria-label={menuOpen ? 'Close customer navigation' : 'Open customer navigation'}
        aria-controls="customer-navigation"
        aria-expanded={menuOpen}
        onClick={() => setMenuOpen(!menuOpen)}
      >
        {menuOpen ? <X size={20} /> : <Menu size={20} />}
      </button>
      <nav
        id="customer-navigation"
        className={menuOpen ? 'is-open' : ''}
        aria-label="Customer navigation"
        onClick={(event) => {
          if (event.target instanceof Element && event.target.closest('a, button')) {
            setMenuOpen(false)
          }
        }}
      >
        <Link to="/vehicles">Explore vehicles</Link>
        <CustomerAccountNavigation />
      </nav>
    </header>
  )
}
