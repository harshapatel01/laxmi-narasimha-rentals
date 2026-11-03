import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToString } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

import { HomePage } from './App'
import { CustomerSiteHeader } from './components/CustomerSiteHeader'
import { PublicVehicleListPage } from './pages/VehiclePages'
import { customerSessionQueryKey, refreshCustomerSession } from './services/customerSession'
import { runAfterSuccessfulCustomerRequest } from './utils/customerNavigation'

describe('homepage fleet listings', () => {
  it('keeps the existing search controls and presents data-backed rental benefits', () => {
    const queryClient = new QueryClient()
    queryClient.setQueryData(['api-health'], { status: 'ok', service: 'rentals' })
    queryClient.setQueryData(['featured-vehicles', ''], [])
    queryClient.setQueryData(['public-cities'], [])
    queryClient.setQueryData(['public-categories'], [])

    const markup = renderToString(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <HomePage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(markup).toContain('id="search-city"')
    expect(markup).toContain('id="pickup-date"')
    expect(markup).toContain('id="rental-duration"')
    expect(markup).toContain('Choose your pickup')
    expect(markup).toContain('Rent your way')
    expect(markup).toContain('Local support')
    expect(markup).toContain('href="/vehicles"')
    queryClient.clear()
  })

  it('renders vehicle cards supplied by the live public fleet query', () => {
    const queryClient = new QueryClient()
    const vehicleId = 'c0d0a57b-2be2-4c65-99a6-dc2a503de342'
    queryClient.setQueryData(['api-health'], { status: 'ok', service: 'rentals' })
    queryClient.setQueryData(['featured-vehicles', ''], [{
      id: vehicleId,
      brand: 'Honda',
      model: 'Activa',
      category_name: 'Scooter',
      city_id: 'a1f49e79-0d16-4f69-980b-310311def0d1',
      city_name: 'Hyderabad',
      daily_rental_enabled: true,
      daily_base_price: '900.00',
      hourly_rental_enabled: false,
      hourly_base_price: null,
      images: [],
    }])
    queryClient.setQueryData(['public-cities'], [])
    queryClient.setQueryData(['public-categories'], [])

    const markup = renderToString(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <HomePage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(markup).toContain('Honda')
    expect(markup).toContain('Activa')
    expect(markup).toContain('Scooter')
    expect(markup).toContain(`href="/vehicles/${vehicleId}"`)
    queryClient.clear()
  })

  it('renders category artwork from live car, bike and other vehicle categories', () => {
    const queryClient = new QueryClient()
    queryClient.setQueryData(['api-health'], { status: 'ok', service: 'rentals' })
    queryClient.setQueryData(['featured-vehicles', ''], [])
    queryClient.setQueryData(['public-cities'], [])
    queryClient.setQueryData(['public-categories'], [
      { id: 'car-category', name: 'Cars', description: 'City and road trips' },
      { id: 'bike-category', name: 'Bikes', description: 'Easy city rides' },
      { id: 'bus-category', name: 'Minibuses', description: 'Room for the whole crew' },
    ])

    const markup = renderToString(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <HomePage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(markup).toContain('Cars')
    expect(markup).toContain('Bikes')
    expect(markup).toContain('Minibuses')
    expect(markup).toContain('vehicle-artwork-car category-artwork')
    expect(markup).toContain('vehicle-artwork-bike category-artwork')
    expect(markup).toContain('vehicle-artwork-bus category-artwork')
    expect(markup).toContain('category=bike-category')
    expect(markup).toContain('category=bus-category')
    queryClient.clear()
  })

  it('renders customer account navigation from the backend session cache', () => {
    const queryClient = new QueryClient()
    queryClient.setQueryData(customerSessionQueryKey, {
      id: 'customer-1',
      mobile: '+919876543210',
      email: 'customer@example.test',
      mobile_verified: false,
      status: 'active',
      first_name: 'Test',
      last_name: 'Customer',
    })

    const markup = renderToString(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <HomePage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(markup).toContain('My bookings')
    expect(markup).toContain('Explore vehicles')
    expect(markup).toContain('Notifications')
    expect(markup).toContain('My account')
    expect(markup).toContain('Logout')
    expect(markup).not.toContain('Admin sign in')
    expect(markup).not.toContain('Admin')
    expect(markup).not.toContain('Create account')
    expect(markup).not.toContain('Sign in')
    queryClient.clear()
  })

  it.each(['login', 'registration'])(
    'renders the authenticated header after verified %s',
    async () => {
      const queryClient = new QueryClient()
      const customer = {
        id: 'customer-after-auth',
        mobile: '+919876543210',
        email: 'customer@example.test',
        mobile_verified: false,
        status: 'active',
        first_name: 'Test',
        last_name: 'Customer',
      }
      const fetchMock = vi.fn().mockResolvedValue(
        new Response(JSON.stringify(customer), { status: 200 }),
      )
      vi.stubGlobal('fetch', fetchMock)

      await runAfterSuccessfulCustomerRequest(
        async () => ({ id: 'auth-endpoint-response' }),
        async () => {
          await refreshCustomerSession(queryClient)
        },
      )

      const markup = renderToString(
        <QueryClientProvider client={queryClient}>
          <MemoryRouter>
            <CustomerSiteHeader />
          </MemoryRouter>
        </QueryClientProvider>,
      )

      expect(String(fetchMock.mock.calls[0][0])).toContain('/api/v1/auth/me')
      expect(markup).toContain('My bookings')
      expect(markup).toContain('Notifications')
      expect(markup).toContain('My account')
      expect(markup).toContain('Logout')
      expect(markup).not.toContain('Customer sign in')
      expect(markup).not.toContain('Create account')
      vi.unstubAllGlobals()
      queryClient.clear()
    },
  )

  it('renders sign-in links only after an anonymous session result', () => {
    const queryClient = new QueryClient()
    queryClient.setQueryData(customerSessionQueryKey, null)

    const markup = renderToString(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <HomePage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(markup).toContain('Customer sign in')
    expect(markup).toContain('Create account')
    expect(markup).toContain('Admin')
    queryClient.clear()
  })

  it('keeps admin login hidden while the customer session is being verified', () => {
    const queryClient = new QueryClient()
    const markup = renderToString(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <HomePage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(markup).toContain('Checking session')
    expect(markup).toContain('Explore vehicles')
    expect(markup).not.toContain('Admin sign in')
    expect(markup).not.toContain('href="/admin/login"')
    queryClient.clear()
  })

  it('uses the shared authenticated navigation on the public vehicle listing', () => {
    const queryClient = new QueryClient()
    queryClient.setQueryData(customerSessionQueryKey, {
      id: 'customer-1',
      mobile: '+919876543210',
      email: 'customer@example.test',
      mobile_verified: false,
      status: 'active',
      first_name: 'Test',
      last_name: 'Customer',
    })

    const markup = renderToString(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/vehicles?city=city-a&category=category-b']}>
          <PublicVehicleListPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(markup).toContain('Explore vehicles')
    expect(markup).toContain('My bookings')
    expect(markup).toContain('Notifications')
    expect(markup).toContain('My account')
    expect(markup).toContain('Logout')
    expect(markup).not.toContain('Admin')
    expect(markup).not.toContain('Customer sign in')
    expect(markup).not.toContain('Create account')
    expect(markup).toContain('Category')
    queryClient.clear()
  })

  it('uses the public logged-out navigation on vehicle listing', () => {
    const queryClient = new QueryClient()
    queryClient.setQueryData(customerSessionQueryKey, null)

    const markup = renderToString(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={['/vehicles']}>
          <PublicVehicleListPage />
        </MemoryRouter>
      </QueryClientProvider>,
    )

    expect(markup).toContain('Customer sign in')
    expect(markup).toContain('Create account')
    expect(markup).toContain('Admin')
    expect(markup).not.toContain('My bookings')
    queryClient.clear()
  })
})
