import { describe, expect, it, vi } from 'vitest'

import {
  customerPostAuthDestination,
  runAfterSuccessfulCustomerRequest,
} from './customerNavigation'

describe('customer post-auth navigation', () => {
  const origin = 'https://rentals.example'

  it('defaults registration and login to the new homepage', () => {
    expect(customerPostAuthDestination(null, origin)).toBe('/')
    expect(customerPostAuthDestination('', origin)).toBe('/')
  })

  it('preserves a safe internal booking destination after login', () => {
    expect(customerPostAuthDestination(
      '/vehicles/c0d0a57b-2be2-4c65-99a6-dc2a503de342/book?city=stale',
      origin,
    )).toBe('/vehicles/c0d0a57b-2be2-4c65-99a6-dc2a503de342/book')
  })

  it('clears stale city and category filters when returning to vehicle search', () => {
    expect(customerPostAuthDestination('/vehicles?city=inactive&category=old', origin))
      .toBe('/vehicles')
  })

  it.each([
    'https://attacker.example',
    '//attacker.example/path',
    '/\\attacker.example',
    '/admin',
    '/vehicles/not-a-vehicle/book',
  ])('rejects unsafe post-login target %s', (next) => {
    expect(customerPostAuthDestination(next, origin)).toBe('/')
  })

  it('only runs the login redirect after a successful authentication request', async () => {
    const navigate = vi.fn()
    const verifySession = vi.fn(async () => {
      await Promise.resolve()
    })
    await runAfterSuccessfulCustomerRequest(
      async () => ({ id: 'customer-id' }),
      async () => {
        await verifySession()
        navigate(customerPostAuthDestination(
          '/vehicles/c0d0a57b-2be2-4c65-99a6-dc2a503de342/book',
          origin,
        ))
      },
    )
    expect(verifySession).toHaveBeenCalledOnce()
    expect(navigate).toHaveBeenCalledExactlyOnceWith(
      '/vehicles/c0d0a57b-2be2-4c65-99a6-dc2a503de342/book',
    )

    navigate.mockClear()
    await expect(runAfterSuccessfulCustomerRequest(
      async () => { throw new Error('Invalid credentials') },
      () => navigate('/'),
    )).rejects.toThrow('Invalid credentials')
    expect(navigate).not.toHaveBeenCalled()
  })

  it('only redirects registration to the homepage after account creation succeeds', async () => {
    const navigate = vi.fn()
    await runAfterSuccessfulCustomerRequest(
      async () => ({ id: 'new-customer' }),
      () => navigate('/'),
    )
    expect(navigate).toHaveBeenCalledExactlyOnceWith('/')

    navigate.mockClear()
    await expect(runAfterSuccessfulCustomerRequest(
      async () => { throw new Error('Email already registered') },
      () => navigate('/'),
    )).rejects.toThrow('Email already registered')
    expect(navigate).not.toHaveBeenCalled()
  })
})
