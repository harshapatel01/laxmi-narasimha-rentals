import { describe, expect, it } from 'vitest'
import {
  apiErrorMessage,
  clearCsrfTokenForRequest,
  csrfTokenForRequest,
  updateCsrfTokenFromResponse,
} from './requestUtils'

describe('csrfTokenForRequest', () => {
  it('uses the admin CSRF cookie for admin mutations when both sessions exist', () => {
    const cookies = 'lnr_customer_csrf=customer-token; lnr_admin_csrf=admin-token'

    expect(csrfTokenForRequest('/admin/pickup-locations', cookies)).toBe('admin-token')
  })

  it('uses the customer CSRF cookie for customer mutations', () => {
    const cookies = 'lnr_admin_csrf=admin-token; lnr_customer_csrf=customer-token'

    expect(csrfTokenForRequest('/auth/logout', cookies)).toBe('customer-token')
  })

  it('does not substitute one session type for the other', () => {
    expect(csrfTokenForRequest('/admin/cities', 'lnr_customer_csrf=customer-token')).toBeUndefined()
  })

  it('decodes an encoded CSRF cookie value', () => {
    expect(csrfTokenForRequest('/admin/cities', 'lnr_admin_csrf=token%2Bvalue')).toBe('token+value')
  })

  it('keeps customer and admin tokens separate and prefers tokens returned by the API', () => {
    updateCsrfTokenFromResponse('/auth/me', new Response(null, {
      status: 200,
      headers: { 'X-CSRF-Token': 'customer-header-token' },
    }))
    updateCsrfTokenFromResponse('/admin/auth/me', new Response(null, {
      status: 200,
      headers: { 'X-CSRF-Token': 'admin-header-token' },
    }))

    expect(csrfTokenForRequest('/bookings', '')).toBe('customer-header-token')
    expect(csrfTokenForRequest('/admin/bookings', '')).toBe('admin-header-token')

    clearCsrfTokenForRequest('/auth/me')
    clearCsrfTokenForRequest('/admin/auth/me')
  })
})

describe('apiErrorMessage', () => {
  it('shows field-level FastAPI validation errors without exposing submitted values', () => {
    expect(apiErrorMessage({
      detail: [
        { loc: ['body', 'city_id'], msg: 'Input should be a valid UUID', input: 'secret-value' },
        { loc: ['body', 'address'], msg: 'Field required' },
      ],
    }, 422)).toBe('Please correct the following: city_id: Input should be a valid UUID; address: Field required')
  })

  it('preserves string API error details', () => {
    expect(apiErrorMessage({ detail: 'CSRF validation failed.' }, 403)).toBe('CSRF validation failed.')
  })
})
