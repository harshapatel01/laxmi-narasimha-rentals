import { type ChangeEvent, type FormEvent, type ReactNode, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  ArrowLeft,
  ArrowRight,
  CarFront,
  Check,
  Fuel,
  MapPin,
  Plus,
  Search,
  Settings2,
  Users,
  X,
} from 'lucide-react'

import { apiAssetUrl, apiRequest, ApiError } from '../services/api'
import { CustomerSiteHeader } from '../components/CustomerSiteHeader'
import { AdminPasswordConfirmationDialog } from '../components/AdminPasswordConfirmationDialog'
import { VehicleArtwork } from '../components/VehicleArtwork'
import { suggestedSeatingCapacity } from '../utils/vehicleDefaults'

interface City {
  id: string
  name: string
  state: string
  is_active: boolean
}

interface Category {
  id: string
  name: string
  description: string | null
  is_active: boolean
}

interface PickupLocation {
  id: string
  city_id: string
  city_name: string
  name: string
  address: string
  google_maps_url: string | null
  is_active: boolean
}

interface AdminVehicleDashboard {
  as_of: string
  business_timezone: string
  fleet_vehicle_count: number
  currently_on_rent_count: number
  currently_on_rent: Array<{
    vehicle_id: string
    vehicle_name: string
    registration_number: string
    customer_name: string
    customer_mobile: string
    booking_reference: string
    pickup_at: string
    return_at: string
  }>
  upcoming_booking_count: number
  upcoming_bookings: Array<{
    vehicle_id: string
    vehicle_name: string
    registration_number: string
    customer_name: string
    customer_mobile: string
    booking_reference: string
    pickup_at: string
    return_at: string
  }>
  available_now_count: number
  available_now: Array<{
    vehicle_id: string
    vehicle_name: string
    registration_number: string
    city: string
    category: string
    pickup_location: string
  }>
}

interface VehicleImage {
  id: string
  image_path: string
  is_primary: boolean
  display_order: number
}

interface Vehicle {
  id: string
  vehicle_code: string
  brand: string
  model: string
  variant: string | null
  manufacturing_year: number
  registration_number: string
  category_id: string
  category_name: string
  city_id: string
  city_name: string
  pickup_location_id: string
  pickup_location_name: string
  pickup_address: string
  google_maps_url: string | null
  seating_capacity: number
  fuel_type: string
  transmission_type: string
  self_drive_enabled: boolean
  with_driver_enabled: boolean
  hourly_rental_enabled: boolean
  daily_rental_enabled: boolean
  custom_trip_enabled: boolean
  hourly_base_price: string | null
  daily_base_price: string | null
  advance_payment_amount: string
  description: string | null
  is_active: boolean
  availability_status: 'available' | 'maintenance' | 'inactive'
  images: VehicleImage[]
}

interface VehicleFormData {
  vehicle_code: string
  brand: string
  model: string
  variant: string
  manufacturing_year: string
  registration_number: string
  category_id: string
  city_id: string
  pickup_location_id: string
  seating_capacity: string
  fuel_type: string
  transmission_type: string
  self_drive_enabled: boolean
  with_driver_enabled: boolean
  hourly_rental_enabled: boolean
  daily_rental_enabled: boolean
  custom_trip_enabled: boolean
  hourly_base_price: string
  daily_base_price: string
  advance_payment_amount: string
  description: string
  availability_status: 'available' | 'maintenance' | 'inactive'
}

const maximumManufacturingYear = new Date().getFullYear() + 1

const emptyVehicle: VehicleFormData = {
  vehicle_code: '',
  brand: '',
  model: '',
  variant: '',
  manufacturing_year: String(new Date().getFullYear()),
  registration_number: '',
  category_id: '',
  city_id: '',
  pickup_location_id: '',
  seating_capacity: '5',
  fuel_type: 'petrol',
  transmission_type: 'manual',
  self_drive_enabled: true,
  with_driver_enabled: false,
  hourly_rental_enabled: false,
  daily_rental_enabled: true,
  custom_trip_enabled: false,
  hourly_base_price: '',
  daily_base_price: '',
  advance_payment_amount: '0.00',
  description: '',
  availability_status: 'available',
}

function messageFor(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message
  return 'The request could not be completed. Please try again.'
}

function useAdminGuard() {
  const navigate = useNavigate()
  const [ready, setReady] = useState(false)
  useEffect(() => {
    apiRequest('/admin/auth/me')
      .then(() => setReady(true))
      .catch((error: unknown) => {
        navigate(error instanceof ApiError && error.status === 401 ? '/session-expired' : '/unauthorized', { replace: true })
      })
  }, [navigate])
  return ready
}

function AdminLayout({ children, title, description, active }: {
  children: ReactNode
  title: string
  description: string
  active: string
}) {
  const links = [
    { to: '/admin', label: 'Dashboard' },
    { to: '/admin/bookings', label: 'Bookings' },
    { to: '/admin/customers', label: 'Customers' },
    { to: '/admin/vehicles', label: 'Vehicles' },
    { to: '/admin/vehicles/new', label: 'Add Vehicle' },
    { to: '/admin/categories', label: 'Categories' },
    { to: '/admin/cities', label: 'Cities' },
    { to: '/admin/pickup-locations', label: 'Pickup Locations' },
  ]
  return (
    <main className="vehicle-admin-page">
      <header className="vehicle-admin-header">
        <Link className="brand" to="/" aria-label="Laxmi Narasimha Rentals home">
          <span className="brand-mark">LN</span>
          <span className="brand-name"><strong>LAXMI NARASIMHA</strong><small>RENTALS</small></span>
        </Link>
        <Link to="/" className="vehicle-admin-back"><ArrowLeft size={15} /> Public site</Link>
      </header>
      <div className="vehicle-admin-shell">
        <aside className="vehicle-admin-sidebar" aria-label="Admin navigation">
          <div className="sidebar-label">MANAGEMENT</div>
          {links.map(({ to, label }) => (
            <Link key={to} to={to} className={active === to ? 'admin-nav-link active' : 'admin-nav-link'}>
              {label}
            </Link>
          ))}
        </aside>
        <section className="vehicle-admin-content">
          <div className="vehicle-page-heading">
            <div><p className="vehicle-kicker">ADMIN WORKSPACE</p><h1>{title}</h1><p>{description}</p></div>
          </div>
          {children}
        </section>
      </div>
    </main>
  )
}

function Notice({ error, success }: { error: string; success: string }) {
  return (
    <>
      {error && <p className="vehicle-notice error" role="alert">{error}</p>}
      {success && <p className="vehicle-notice success" role="status">{success}</p>}
    </>
  )
}

function useCatalogs() {
  const [cities, setCities] = useState<City[]>([])
  const [categories, setCategories] = useState<Category[]>([])
  const [locations, setLocations] = useState<PickupLocation[]>([])
  const [error, setError] = useState('')

  useEffect(() => {
    Promise.all([
      apiRequest<City[]>('/cities'),
      apiRequest<Category[]>('/categories'),
      apiRequest<PickupLocation[]>('/admin/pickup-locations'),
    ])
      .then(([cityRows, categoryRows, locationRows]) => {
        setCities(cityRows)
        setCategories(categoryRows)
        setLocations(locationRows)
      })
      .catch((requestError: unknown) => setError(messageFor(requestError)))
  }, [])

  return { cities, categories, locations, error }
}

export function AdminVehicleListPage() {
  const ready = useAdminGuard()
  const navigate = useNavigate()
  const { cities, categories } = useCatalogs()
  const [vehicles, setVehicles] = useState<Vehicle[]>([])
  const [cityId, setCityId] = useState('')
  const [categoryId, setCategoryId] = useState('')
  const [availability, setAvailability] = useState('')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [loadedFilterKey, setLoadedFilterKey] = useState<string | null>(null)
  const [pendingVehicleAction, setPendingVehicleAction] = useState<{
    vehicle: Vehicle
    action: 'deactivate' | 'reactivate' | 'delete' | 'restore'
  } | null>(null)
  const [vehicleActionBusy, setVehicleActionBusy] = useState(false)
  const [vehicleActionError, setVehicleActionError] = useState('')
  const filterParams = new URLSearchParams()
  if (cityId) filterParams.set('city_id', cityId)
  if (categoryId) filterParams.set('category_id', categoryId)
  if (availability) filterParams.set('availability_status', availability)
  filterParams.set('include_inactive', 'true')
  const filterKey = filterParams.toString()
  const loading = loadedFilterKey !== filterKey

  useEffect(() => {
    if (!ready) return
    let active = true
    apiRequest<Vehicle[]>(`/admin/vehicles?${filterKey}`)
      .then((rows) => {
        if (active) setVehicles(rows)
      })
      .catch((requestError: unknown) => {
        if (active) setError(messageFor(requestError))
      })
      .finally(() => {
        if (active) setLoadedFilterKey(filterKey)
      })
    return () => {
      active = false
    }
  }, [ready, filterKey])

  async function submitVehicleAction(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!pendingVehicleAction) return
    const form = event.currentTarget
    const formData = new FormData(form)
    const password = String(formData.get('admin-password') ?? '')
    const reason = String(formData.get('reason') ?? '').trim()
    const { vehicle, action } = pendingVehicleAction
    setVehicleActionBusy(true)
    setVehicleActionError('')
    setError('')
    setSuccess('')
    try {
      const updated = await apiRequest<Vehicle>(
        action === 'delete'
          ? `/admin/vehicles/${vehicle.id}`
          : `/admin/vehicles/${vehicle.id}/${action}`,
        {
        method: action === 'delete' ? 'DELETE' : 'POST',
        body: JSON.stringify({ password, reason: reason || null }),
      })
      setSuccess(action === 'delete'
        ? `${vehicle.brand} ${vehicle.model} was deleted safely. Booking and payment history was preserved.`
        : action === 'deactivate'
          ? `${vehicle.brand} ${vehicle.model} was deactivated and can be reactivated.`
          : action === 'reactivate'
            ? `${vehicle.brand} ${vehicle.model} was reactivated and is available for booking.`
            : `${vehicle.brand} ${vehicle.model} was restored from the archive.`)
      setVehicles((current) => current.map((item) => item.id === vehicle.id
        ? updated
        : item))
      setPendingVehicleAction(null)
    } catch (requestError) {
      setVehicleActionError(messageFor(requestError))
    } finally {
      form.reset()
      setVehicleActionBusy(false)
    }
  }

  function closeVehicleAction() {
    setPendingVehicleAction(null)
    setVehicleActionError('')
  }

  if (!ready) return <p className="vehicle-loading">Checking admin session…</p>
  return (
    <AdminLayout active="/admin/vehicles" title="Vehicles" description="Manage your fleet, pricing, images, and availability.">
      <div className="vehicle-toolbar">
        <div className="vehicle-filter">
          <label htmlFor="fleet-city-filter">City</label>
          <select id="fleet-city-filter" value={cityId} onChange={(event) => setCityId(event.target.value)}>
            <option value="">All cities</option>
            {cities.map((city) => <option key={city.id} value={city.id}>{city.name}</option>)}
          </select>
        </div>
        <div className="vehicle-filter">
          <label htmlFor="fleet-category-filter">Category</label>
          <select id="fleet-category-filter" value={categoryId} onChange={(event) => setCategoryId(event.target.value)}>
            <option value="">All categories</option>
            {categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}
          </select>
        </div>
        <div className="vehicle-filter">
          <label htmlFor="fleet-status-filter">Status</label>
          <select id="fleet-status-filter" value={availability} onChange={(event) => setAvailability(event.target.value)}>
            <option value="">All statuses</option>
            <option value="available">Available</option>
            <option value="maintenance">Maintenance</option>
            <option value="inactive">Inactive</option>
          </select>
        </div>
        <Link to="/admin/vehicles/new" className="vehicle-primary-button"><Plus size={16} /> Add vehicle</Link>
      </div>
      <Notice error={error} success={success} />
      {loading ? <p className="vehicle-loading">Loading fleet…</p> : (
        <div className="vehicle-table-wrap">
          <table className="vehicle-table">
            <thead><tr><th>Vehicle</th><th>City</th><th>Category</th><th>Pricing</th><th>Status</th><th>Actions</th></tr></thead>
            <tbody>
              {vehicles.map((vehicle) => (
                <tr key={vehicle.id}>
                  <td><div className="vehicle-table-name">
                    {vehicle.images.find((image) => image.is_primary) && <img src={apiAssetUrl(vehicle.images.find((image) => image.is_primary)!.image_path)} alt="" />}
                    <span><strong>{vehicle.brand} {vehicle.model}</strong><small>{vehicle.vehicle_code} · {vehicle.registration_number}</small></span>
                  </div></td>
                  <td>{vehicle.city_name}</td><td>{vehicle.category_name}</td>
                  <td>{vehicle.daily_rental_enabled ? `₹${vehicle.daily_base_price}/day` : 'Custom pricing'}</td>
                  <td><span className={`vehicle-status ${vehicle.availability_status}`}>{!vehicle.is_active ? 'deleted' : vehicle.availability_status === 'inactive' ? 'deactivated' : vehicle.availability_status}</span>{!vehicle.is_active && <small className="inactive-label">Archived</small>}</td>
                  <td><div className="table-actions">
                    <button type="button" className="table-action" onClick={() => navigate(`/admin/vehicles/${vehicle.id}/edit`)}>Edit</button>
                    {vehicle.is_active && vehicle.availability_status !== 'inactive' && <button type="button" className="table-action danger" onClick={() => {
                      setVehicleActionError('')
                      setPendingVehicleAction({ vehicle, action: 'deactivate' })
                    }}>Deactivate vehicle</button>}
                    {vehicle.is_active && vehicle.availability_status === 'inactive' && <button type="button" className="table-action" onClick={() => {
                      setVehicleActionError('')
                      setPendingVehicleAction({ vehicle, action: 'reactivate' })
                    }}>Reactivate vehicle</button>}
                    {vehicle.is_active && <button type="button" className="table-action danger" onClick={() => {
                      setVehicleActionError('')
                      setPendingVehicleAction({ vehicle, action: 'delete' })
                    }}>Delete vehicle</button>}
                    {!vehicle.is_active && <button type="button" className="table-action" onClick={() => {
                      setVehicleActionError('')
                      setPendingVehicleAction({ vehicle, action: 'restore' })
                    }}>Reactivate archived vehicle</button>}
                  </div></td>
                </tr>
              ))}
              {vehicles.length === 0 && <tr><td className="empty-table" colSpan={6}>No vehicles match these filters. Add your first vehicle to begin.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
      {pendingVehicleAction && (
        <AdminPasswordConfirmationDialog
          idPrefix="vehicle-action"
          title={{
            deactivate: 'Deactivate this vehicle?',
            reactivate: 'Reactivate this vehicle?',
            delete: 'Delete this vehicle?',
            restore: 'Restore this archived vehicle?',
          }[pendingVehicleAction.action]}
          identityTitle={`${pendingVehicleAction.vehicle.brand} ${pendingVehicleAction.vehicle.model}`}
          identityDetail={`${pendingVehicleAction.vehicle.vehicle_code} · ${pendingVehicleAction.vehicle.registration_number}`}
          description={{
            deactivate: 'The vehicle will remain in your fleet but will be unavailable to customers. You can reactivate it later.',
            reactivate: 'The vehicle will become available to customers for booking.',
            delete: 'The vehicle will be archived and removed from customer listings. Vehicle, booking, payment, and image history will be preserved.',
            restore: 'The archived vehicle will be restored. If it is in maintenance, it will remain unavailable for customer bookings.',
          }[pendingVehicleAction.action]}
          submitLabel={{
            deactivate: 'Confirm deactivation',
            reactivate: 'Confirm reactivation',
            delete: 'Confirm deletion',
            restore: 'Confirm restore',
          }[pendingVehicleAction.action]}
          error={vehicleActionError}
          busy={vehicleActionBusy}
          onSubmit={(event) => void submitVehicleAction(event)}
          onCancel={closeVehicleAction}
        />
      )}
    </AdminLayout>
  )
}

interface AdminCustomer {
  id: string
  full_name: string | null
  email: string | null
  mobile: string
  status: string
  created_at: string
}

interface CustomerBooking {
  id: string
  reference: string
  vehicle_name: string
  status: string
  start_at: string
  end_at: string
  estimated_total: string | null
}

export function AdminCustomersPage() {
  const ready = useAdminGuard()
  const [search, setSearch] = useState('')
  const [customers, setCustomers] = useState<AdminCustomer[]>([])
  const [loadedSearch, setLoadedSearch] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [pendingAction, setPendingAction] = useState<{
    customer: AdminCustomer
    action: 'block' | 'unblock' | 'deactivate' | 'reactivate' | 'delete'
  } | null>(null)
  const [submittingStatusChange, setSubmittingStatusChange] = useState(false)
  const [confirmationError, setConfirmationError] = useState('')
  const [historyCustomerId, setHistoryCustomerId] = useState<string | null>(null)
  const [history, setHistory] = useState<CustomerBooking[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const loading = loadedSearch !== search

  useEffect(() => {
    if (!ready) return
    let active = true
    const query = search.trim()
    apiRequest<AdminCustomer[]>(`/admin/customers${query ? `?q=${encodeURIComponent(query)}` : ''}`)
      .then((rows) => {
        if (active) {
          setCustomers(rows)
          setError('')
        }
      })
      .catch((requestError: unknown) => {
        if (active) setError(messageFor(requestError))
      })
      .finally(() => {
        if (active) setLoadedSearch(search)
      })
    return () => { active = false }
  }, [ready, search])

  async function showBookingHistory(customer: AdminCustomer) {
    if (historyCustomerId === customer.id) {
      setHistoryCustomerId(null)
      return
    }
    setHistoryCustomerId(customer.id)
    setHistoryLoading(true)
    setError('')
    try {
      const rows = await apiRequest<CustomerBooking[]>(`/admin/customers/${customer.id}/bookings`)
      setHistory(rows)
    } catch (requestError) {
      setError(messageFor(requestError))
    } finally {
      setHistoryLoading(false)
    }
  }

  async function submitStatusChange(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!pendingAction) return
    const form = event.currentTarget
    const formData = new FormData(form)
    const password = String(formData.get('admin-password') ?? '')
    const reason = String(formData.get('reason') ?? '').trim()
    const requestUrl = `/admin/customers/${pendingAction.customer.id}${
      pendingAction.action === 'delete' ? '' : `/${pendingAction.action}`
    }`
    setSubmittingStatusChange(true)
    setConfirmationError('')
    setError('')
    setSuccess('')
    try {
      const updated = await apiRequest<AdminCustomer>(
        requestUrl,
        {
          method: pendingAction.action === 'delete' ? 'DELETE' : 'POST',
          body: JSON.stringify({ password, reason: reason || null }),
        },
      )
      setCustomers((current) => current.map((row) => row.id === updated.id ? updated : row))
      const actionLabel = {
        delete: 'deleted safely',
        deactivate: 'deactivated',
        reactivate: 'reactivated',
        block: 'blocked',
        unblock: 'unblocked',
      }[pendingAction.action]
      setSuccess(`${updated.full_name || updated.email || updated.mobile} was ${actionLabel}.`)
      setPendingAction(null)
    } catch (requestError) {
      setConfirmationError(messageFor(requestError))
    } finally {
      form.reset()
      setSubmittingStatusChange(false)
    }
  }

  function closeStatusDialog() {
    setPendingAction(null)
    setConfirmationError('')
  }

  if (!ready) return <p className="vehicle-loading">Checking admin session…</p>
  return (
    <AdminLayout active="/admin/customers" title="Customers" description="Search customer accounts, review booking history, and manage account access.">
      <div className="vehicle-toolbar customer-toolbar">
        <label className="vehicle-filter customer-search" htmlFor="customer-search">
          Search name, email, or mobile
          <span className="customer-search-input"><Search size={16} /><input id="customer-search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search customers" /></span>
        </label>
      </div>
      <Notice error={error} success={success} />
      {loading ? <p className="vehicle-loading">Loading customers…</p> : (
        <div className="vehicle-table-wrap">
          <table className="vehicle-table customer-table">
            <thead><tr><th>Customer</th><th>Mobile</th><th>Status</th><th>Registered</th><th>Actions</th></tr></thead>
            <tbody>
              {customers.map((customer) => (
                <tr key={customer.id}>
                  <td><span className="customer-identity"><strong>{customer.full_name || 'Name not provided'}</strong><small>{customer.email || 'No email set'}</small></span></td>
                  <td>{customer.mobile}</td>
                  <td><span className={`customer-status ${customer.status}`}>{customer.status === 'active' ? 'Active' : customer.status === 'blocked' ? 'Blocked' : customer.status === 'deleted' ? 'Deleted' : 'Deactivated'}</span></td>
                  <td>{new Date(customer.created_at).toLocaleDateString()}</td>
                  <td><div className="table-actions">
                    <button type="button" className="table-action" onClick={() => void showBookingHistory(customer)}>
                      {historyCustomerId === customer.id ? 'Hide bookings' : 'Booking history'}
                    </button>
                    {customer.status === 'active' && <button
                      type="button"
                      className="table-action danger"
                      onClick={() => {
                        setConfirmationError('')
                        setPendingAction({ customer, action: 'deactivate' })
                      }}
                    >
                      Deactivate customer
                    </button>}
                    {customer.status === 'deactivated' && <button
                      type="button"
                      className="table-action"
                      onClick={() => {
                        setConfirmationError('')
                        setPendingAction({ customer, action: 'reactivate' })
                      }}
                    >
                      Reactivate customer
                    </button>}
                    {customer.status !== 'deleted' && <button
                      type="button"
                      className="table-action danger"
                      onClick={() => {
                        setConfirmationError('')
                        setPendingAction({ customer, action: 'delete' })
                      }}
                    >
                      Delete customer
                    </button>}
                    {customer.status === 'active' && <button
                      type="button"
                      className="table-action danger"
                      onClick={() => {
                        setConfirmationError('')
                        setPendingAction({ customer, action: 'block' })
                      }}
                    >
                      Block customer
                    </button>}
                    {customer.status === 'blocked' && <button
                      type="button"
                      className="table-action"
                      onClick={() => {
                        setConfirmationError('')
                        setPendingAction({ customer, action: 'unblock' })
                      }}
                    >
                      Unblock customer
                    </button>}
                  </div></td>
                </tr>
              ))}
              {historyCustomerId && (
                <tr className="customer-bookings-row">
                  <td colSpan={5}>
                    {historyLoading ? <p className="vehicle-loading">Loading booking history…</p> : history.length ? (
                      <ul className="customer-booking-list">
                        {history.map((booking) => (
                          <li key={booking.id}>
                            <strong>{booking.reference}</strong>
                            <span>{booking.vehicle_name} · {booking.status}</span>
                            <span>{new Date(booking.start_at).toLocaleString()} – {new Date(booking.end_at).toLocaleString()}</span>
                          </li>
                        ))}
                      </ul>
                    ) : <p>No bookings found for this customer.</p>}
                  </td>
                </tr>
              )}
              {customers.length === 0 && <tr><td className="empty-table" colSpan={5}>No customers match this search.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
      {pendingAction && (
        <AdminPasswordConfirmationDialog
          idPrefix="customer-action"
          title={{
            delete: 'Delete this customer?',
            deactivate: 'Deactivate this customer?',
            reactivate: 'Reactivate this customer?',
            block: 'Block this customer?',
            unblock: 'Unblock this customer?',
          }[pendingAction.action]}
          identityTitle={pendingAction.customer.full_name || 'Name not provided'}
          identityDetail={pendingAction.customer.email || 'No email set'}
          description={{
            delete: 'The account will be permanently marked deleted and signed out. The account record and profile are retained; booking, payment, and audit history will not be removed. This action cannot be undone.',
            deactivate: 'The account will remain in the database, be signed out, and be unable to log in or create bookings. You can reactivate it later.',
            reactivate: 'The customer will be able to sign in again. Existing sessions remain revoked.',
            block: 'The customer will be signed out and will not be able to access their account or create bookings.',
            unblock: 'The customer will be able to sign in again. Their previous sessions will remain revoked.',
          }[pendingAction.action]}
          submitLabel={{
            delete: 'Confirm deletion',
            deactivate: 'Confirm deactivation',
            reactivate: 'Confirm reactivation',
            block: 'Confirm block',
            unblock: 'Confirm unblock',
          }[pendingAction.action]}
          error={confirmationError}
          busy={submittingStatusChange}
          onSubmit={submitStatusChange}
          onCancel={closeStatusDialog}
        />
      )}
    </AdminLayout>
  )
}

export function AdminHomePage() {
  const ready = useAdminGuard()
  const [admin, setAdmin] = useState<{ username: string; role: string } | null>(null)
  const [dashboard, setDashboard] = useState<AdminVehicleDashboard | null>(null)
  const [statsLoading, setStatsLoading] = useState(true)
  const [statsRefreshing, setStatsRefreshing] = useState(false)
  const [statsError, setStatsError] = useState('')
  const [statsRefreshKey, setStatsRefreshKey] = useState(0)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!ready) return
    let active = true
    apiRequest<{ username: string; role: string }>('/admin/auth/me')
      .then((currentAdmin) => { if (active) setAdmin(currentAdmin) })
      .catch((requestError: unknown) => { if (active) setError(messageFor(requestError)) })

    async function refreshVehicleStats() {
      if (!active) return
      setStatsRefreshing(true)
      try {
        const stats = await apiRequest<AdminVehicleDashboard>('/admin/dashboard/vehicle-stats')
        if (active) {
          setDashboard(stats)
          setStatsError('')
          setStatsLoading(false)
        }
      } catch (requestError) {
        if (active) {
          setStatsError(messageFor(requestError))
          setStatsLoading(false)
        }
      } finally {
        if (active) setStatsRefreshing(false)
      }
    }

    void refreshVehicleStats()
    const interval = window.setInterval(() => {
      if (!document.hidden) void refreshVehicleStats()
    }, 15_000)
    const onFocus = () => { void refreshVehicleStats() }
    window.addEventListener('focus', onFocus)
    return () => {
      active = false
      window.clearInterval(interval)
      window.removeEventListener('focus', onFocus)
    }
  }, [ready, statsRefreshKey])

  if (!ready) return <p className="vehicle-loading">Checking admin session…</p>
  return (
    <AdminLayout active="/admin" title="Operations overview" description={admin ? `Welcome back, ${admin.username}. Manage your fleet and service areas.` : 'Manage your fleet and service areas.'}>
      <Notice error={error} success="" />
      <div className="admin-overview-grid">
        <article className="admin-overview-card"><span>Fleet vehicles</span><strong>{dashboard?.fleet_vehicle_count ?? '—'}</strong><Link to="/admin/vehicles">View vehicles <ArrowRight size={14} /></Link></article>
        <article className="admin-overview-card"><span>Administrator role</span><strong>{admin?.role ?? '—'}</strong><small>Protected admin workspace</small></article>
        <article className="admin-overview-card"><span>Quick action</span><strong>Add a vehicle</strong><Link to="/admin/vehicles/new">Open vehicle form <ArrowRight size={14} /></Link></article>
      </div>
      <div className="admin-overview-panel">
        <h2>Fleet setup</h2>
        <p>Start by creating your cities, vehicle categories, and pickup locations. Then add vehicles to your fleet.</p>
        <div className="admin-overview-links">
          <Link to="/admin/cities"><MapPin size={17} /> Manage cities</Link>
          <Link to="/admin/categories"><CarFront size={17} /> Manage categories</Link>
          <Link to="/admin/pickup-locations"><MapPin size={17} /> Pickup locations</Link>
          <Link to="/admin/vehicles/new"><Plus size={17} /> Add vehicle</Link>
        </div>
      </div>
      <section className="admin-live-fleet" aria-labelledby="admin-live-fleet-title">
        <div className="admin-live-fleet-heading">
          <div>
            <h2 id="admin-live-fleet-title">Fleet availability now</h2>
            <p>
              {dashboard ? (
                <>
                  As of {new Intl.DateTimeFormat('en-IN', {
                  dateStyle: 'medium',
                  timeStyle: 'short',
                  timeZone: dashboard.business_timezone,
                  }).format(new Date(dashboard.as_of))} ({dashboard.business_timezone}). Availability shown here is for now, not a future date.
                  Pending requests do not reserve vehicles.
                </>
              ) : 'Live fleet status in India Standard Time.'}
            </p>
          </div>
          <button
            type="button"
            className="vehicle-secondary-button"
            onClick={() => setStatsRefreshKey((key) => key + 1)}
            disabled={statsRefreshing}
          >
            {statsRefreshing ? 'Refreshing…' : 'Refresh status'}
          </button>
        </div>
        {statsLoading && <p className="vehicle-loading" role="status">Loading current fleet availability…</p>}
        {!statsLoading && statsError && <p className="vehicle-notice error" role="alert">Fleet availability could not be loaded: {statsError}</p>}
        {!statsLoading && !statsError && dashboard && (
          <div className="admin-live-fleet-grid">
            <section className="admin-live-fleet-card" aria-labelledby="admin-rentals-title">
              <div className="admin-live-fleet-count">
                <h3 id="admin-rentals-title">Vehicles currently on rent</h3>
                <strong>{dashboard.currently_on_rent_count}</strong>
              </div>
              <p className="admin-live-fleet-definition">Confirmed bookings where pickup time is at or before now and return time is after now.</p>
              {dashboard.currently_on_rent.length === 0
                ? <p className="admin-live-fleet-empty">No vehicles are currently on rent.</p>
                : <ul className="admin-live-fleet-list">{dashboard.currently_on_rent.map((rental) => (
                  <li key={`${rental.vehicle_id}:${rental.booking_reference}`}>
                    <strong>{rental.vehicle_name}</strong>
                    <span>{rental.registration_number} · {rental.customer_name} ({rental.customer_mobile})</span>
                    <span>Booking {rental.booking_reference}</span>
                    <span>Pickup {new Intl.DateTimeFormat('en-IN', { dateStyle: 'medium', timeStyle: 'short', timeZone: dashboard.business_timezone }).format(new Date(rental.pickup_at))}</span>
                    <span>Return {new Intl.DateTimeFormat('en-IN', { dateStyle: 'medium', timeStyle: 'short', timeZone: dashboard.business_timezone }).format(new Date(rental.return_at))}</span>
                  </li>
                ))}</ul>}
            </section>
            <section className="admin-live-fleet-card" aria-labelledby="admin-upcoming-title">
              <div className="admin-live-fleet-count">
                <h3 id="admin-upcoming-title">Upcoming confirmed bookings</h3>
                <strong>{dashboard.upcoming_booking_count}</strong>
              </div>
              <p className="admin-live-fleet-definition">Confirmed bookings that start after now. A vehicle in this list can still be available now; check the selected dates before accepting another booking.</p>
              {dashboard.upcoming_bookings.length === 0
                ? <p className="admin-live-fleet-empty">No upcoming confirmed bookings.</p>
                : <ul className="admin-live-fleet-list">{dashboard.upcoming_bookings.map((booking) => (
                  <li key={`${booking.vehicle_id}:${booking.booking_reference}`}>
                    <strong>{booking.vehicle_name}</strong>
                    <span>{booking.registration_number} · {booking.customer_name} ({booking.customer_mobile})</span>
                    <span>Booking {booking.booking_reference}</span>
                    <span>Pickup {new Intl.DateTimeFormat('en-IN', { dateStyle: 'medium', timeStyle: 'short', timeZone: dashboard.business_timezone }).format(new Date(booking.pickup_at))}</span>
                    <span>Return {new Intl.DateTimeFormat('en-IN', { dateStyle: 'medium', timeStyle: 'short', timeZone: dashboard.business_timezone }).format(new Date(booking.return_at))}</span>
                  </li>
                ))}</ul>}
            </section>
            <section className="admin-live-fleet-card" aria-labelledby="admin-available-title">
              <div className="admin-live-fleet-count">
                <h3 id="admin-available-title">Available vehicles now</h3>
                <strong>{dashboard.available_now_count}</strong>
              </div>
              <p className="admin-live-fleet-definition">Active vehicles with eligible catalogs and rental pricing, excluding a confirmed rental active now. A future booking does not make it rented now; verify availability for the requested period.</p>
              {dashboard.available_now.length === 0
                ? <p className="admin-live-fleet-empty">No vehicles are available right now.</p>
                : <ul className="admin-live-fleet-list">{dashboard.available_now.map((vehicle) => (
                  <li key={vehicle.vehicle_id}>
                    <strong>{vehicle.vehicle_name}</strong>
                    <span>{vehicle.registration_number} · {vehicle.city} · {vehicle.category}</span>
                    <span>Pickup: {vehicle.pickup_location}</span>
                  </li>
                ))}</ul>}
            </section>
          </div>
        )}
      </section>
    </AdminLayout>
  )
}

export function VehicleFormPage() {
  const ready = useAdminGuard()
  const navigate = useNavigate()
  const { vehicleId } = useParams()
  const editing = Boolean(vehicleId)
  const { cities, categories, locations, error: catalogError } = useCatalogs()
  const [form, setForm] = useState<VehicleFormData>(emptyVehicle)
  const [images, setImages] = useState<File[]>([])
  const [existingImages, setExistingImages] = useState<VehicleImage[]>([])
  const [previews, setPreviews] = useState<string[]>([])
  const previewUrls = useRef<string[]>([])
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [busy, setBusy] = useState(false)
  const cityLocations = useMemo(() => locations.filter((location) => location.city_id === form.city_id), [locations, form.city_id])

  useEffect(() => {
    if (!ready || !vehicleId) return
    apiRequest<Vehicle>(`/admin/vehicles/${vehicleId}`)
      .then((vehicle) => {
        setForm({
          vehicle_code: vehicle.vehicle_code,
          brand: vehicle.brand,
          model: vehicle.model,
          variant: vehicle.variant ?? '',
          manufacturing_year: String(vehicle.manufacturing_year),
          registration_number: vehicle.registration_number,
          category_id: vehicle.category_id,
          city_id: vehicle.city_id,
          pickup_location_id: vehicle.pickup_location_id,
          seating_capacity: String(vehicle.seating_capacity),
          fuel_type: vehicle.fuel_type,
          transmission_type: vehicle.transmission_type,
          self_drive_enabled: vehicle.self_drive_enabled,
          with_driver_enabled: vehicle.with_driver_enabled,
          hourly_rental_enabled: vehicle.hourly_rental_enabled,
          daily_rental_enabled: vehicle.daily_rental_enabled,
          custom_trip_enabled: vehicle.custom_trip_enabled,
          hourly_base_price: vehicle.hourly_base_price ?? '',
          daily_base_price: vehicle.daily_base_price ?? '',
          advance_payment_amount: vehicle.advance_payment_amount,
          description: vehicle.description ?? '',
          availability_status: vehicle.availability_status,
        })
        setExistingImages(vehicle.images)
      })
      .catch((requestError: unknown) => setError(messageFor(requestError)))
  }, [ready, vehicleId])

  useEffect(() => () => {
    previewUrls.current.forEach((url) => URL.revokeObjectURL(url))
  }, [])

  function update<K extends keyof VehicleFormData>(key: K, value: VehicleFormData[K]) {
    setForm((current) => ({ ...current, [key]: value }))
  }

  function selectImages(event: ChangeEvent<HTMLInputElement>) {
    const selected = Array.from(event.target.files ?? [])
    if (selected.length > 10) {
      setError('Choose no more than 10 images at a time.')
      event.target.value = ''
      return
    }
    if (selected.some((file) => file.size > 8 * 1024 * 1024)) {
      setError('Each image must be 8 MB or smaller.')
      event.target.value = ''
      return
    }
    setError('')
    previewUrls.current.forEach((url) => URL.revokeObjectURL(url))
    previewUrls.current = selected.map((file) => URL.createObjectURL(file))
    setPreviews(previewUrls.current)
    setImages(selected)
  }

  function removeSelectedImage(index: number) {
    const [removedUrl] = previewUrls.current.splice(index, 1)
    if (removedUrl) URL.revokeObjectURL(removedUrl)
    setPreviews([...previewUrls.current])
    setImages((current) => current.filter((_, itemIndex) => itemIndex !== index))
  }

  async function uploadImages(id: string) {
    if (images.length === 0) return
    const body = new FormData()
    images.forEach((image) => body.append('files', image))
    await apiRequest(`/admin/vehicles/${id}/images`, { method: 'POST', body })
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setSuccess('')
    if (!form.city_id || !form.pickup_location_id || !form.category_id) {
      setError('Select a category, city, and pickup location.')
      return
    }
    if (!form.self_drive_enabled && !form.with_driver_enabled) {
      setError('Select self-drive, with-driver, or both service modes.')
      return
    }
    if (!form.hourly_rental_enabled && !form.daily_rental_enabled && !form.custom_trip_enabled) {
      setError('Select at least one rental mode.')
      return
    }
    if (form.hourly_rental_enabled && !form.hourly_base_price) {
      setError('Enter an hourly price for hourly rental.')
      return
    }
    if (form.daily_rental_enabled && !form.daily_base_price) {
      setError('Enter a daily price for daily rental.')
      return
    }
    const payload = {
      ...form,
      hourly_base_price: form.hourly_rental_enabled ? form.hourly_base_price : null,
      daily_base_price: form.daily_rental_enabled ? form.daily_base_price : null,
      variant: form.variant || null,
      description: form.description || null,
      manufacturing_year: Number(form.manufacturing_year),
      seating_capacity: Number(form.seating_capacity),
    }
    setBusy(true)
    try {
      if (editing && vehicleId) {
        await apiRequest(`/admin/vehicles/${vehicleId}`, { method: 'PATCH', body: JSON.stringify(payload) })
        await uploadImages(vehicleId)
        setSuccess('Vehicle details saved.')
      } else {
        const created = await apiRequest<Vehicle>('/admin/vehicles', { method: 'POST', body: JSON.stringify(payload) })
        await uploadImages(created.id)
        setSuccess('Vehicle added to your fleet.')
        navigate(`/admin/vehicles/${created.id}/edit`, { replace: true })
      }
    } catch (requestError) {
      setError(messageFor(requestError))
    } finally {
      setBusy(false)
    }
  }

  async function updateImage(image: VehicleImage, changes: { is_primary?: boolean; display_order?: number }) {
    if (!vehicleId) return
    try {
      const updated = await apiRequest<Vehicle>(`/admin/vehicles/${vehicleId}/images/${image.id}`, {
        method: 'PATCH',
        body: JSON.stringify(changes),
      })
      setExistingImages(updated.images)
    } catch (requestError) {
      setError(messageFor(requestError))
    }
  }

  async function removeImage(image: VehicleImage) {
    if (!vehicleId) return
    try {
      const updated = await apiRequest<Vehicle>(`/admin/vehicles/${vehicleId}/images/${image.id}`, { method: 'DELETE' })
      setExistingImages(updated.images)
    } catch (requestError) {
      setError(messageFor(requestError))
    }
  }

  if (!ready) return <p className="vehicle-loading">Checking admin session…</p>
  return (
    <AdminLayout
      active={editing ? '/admin/vehicles' : '/admin/vehicles/new'}
      title={editing ? 'Edit vehicle' : 'Add vehicle'}
      description={editing ? 'Update fleet details, pricing, images, and availability.' : 'Add a vehicle to your rental fleet.'}
    >
      <Notice error={error || catalogError} success={success} />
      <form className="vehicle-form" onSubmit={(event) => void save(event)}>
        <section className="form-section">
          <h2>Vehicle details</h2>
          <div className="vehicle-form-grid">
            <Field label="Vehicle code" id="vehicle-code"><input id="vehicle-code" required maxLength={40} value={form.vehicle_code} onChange={(event) => update('vehicle_code', event.target.value)} placeholder="HYD-001" /></Field>
            <Field label="Brand" id="vehicle-brand"><input id="vehicle-brand" required maxLength={80} value={form.brand} onChange={(event) => update('brand', event.target.value)} /></Field>
            <Field label="Model" id="vehicle-model"><input id="vehicle-model" required maxLength={100} value={form.model} onChange={(event) => update('model', event.target.value)} /></Field>
            <Field label="Variant (optional)" id="vehicle-variant"><input id="vehicle-variant" maxLength={100} value={form.variant} onChange={(event) => update('variant', event.target.value)} /></Field>
            <Field label="Manufacturing year" id="vehicle-year"><input id="vehicle-year" type="number" min="1900" max={maximumManufacturingYear} required value={form.manufacturing_year} onChange={(event) => update('manufacturing_year', event.target.value)} /></Field>
            <Field label="Registration number" id="vehicle-registration"><input id="vehicle-registration" required maxLength={32} value={form.registration_number} onChange={(event) => update('registration_number', event.target.value)} placeholder="TS 09 AB 1234" /></Field>
            <Field label="Category" id="vehicle-category"><select id="vehicle-category" required value={form.category_id} onChange={(event) => {
              const nextCategory = categories.find((category) => category.id === event.target.value)
              const currentCategory = categories.find((category) => category.id === form.category_id)
              const suggestedSeats = nextCategory ? suggestedSeatingCapacity(nextCategory.name) : undefined
              setForm((current) => ({
                ...current,
                category_id: event.target.value,
                seating_capacity: suggestedSeats !== undefined
                  ? String(suggestedSeats)
                  : currentCategory && suggestedSeatingCapacity(currentCategory.name) !== undefined && current.seating_capacity === '2'
                    ? '5'
                    : current.seating_capacity,
              }))
            }}><option value="">Select category</option>{categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}</select></Field>
            <Field label="City" id="vehicle-city"><select id="vehicle-city" required value={form.city_id} onChange={(event) => { update('city_id', event.target.value); update('pickup_location_id', '') }}><option value="">Select city</option>{cities.map((city) => <option key={city.id} value={city.id}>{city.name}, {city.state}</option>)}</select></Field>
            <Field label="Pickup location" id="vehicle-pickup"><select id="vehicle-pickup" required disabled={!form.city_id} value={form.pickup_location_id} onChange={(event) => update('pickup_location_id', event.target.value)}><option value="">Select pickup location</option>{cityLocations.map((location) => <option key={location.id} value={location.id}>{location.name} — {location.address}</option>)}</select></Field>
            <Field label="Seating capacity" id="vehicle-seats"><input id="vehicle-seats" type="number" min="1" max="100" required value={form.seating_capacity} onChange={(event) => update('seating_capacity', event.target.value)} /></Field>
            <Field label="Fuel type" id="vehicle-fuel"><select id="vehicle-fuel" value={form.fuel_type} onChange={(event) => update('fuel_type', event.target.value)}>{['petrol', 'diesel', 'cng', 'electric', 'hybrid'].map((fuel) => <option key={fuel} value={fuel}>{fuel[0].toUpperCase() + fuel.slice(1)}</option>)}</select></Field>
            <Field label="Transmission" id="vehicle-transmission"><select id="vehicle-transmission" value={form.transmission_type} onChange={(event) => update('transmission_type', event.target.value)}><option value="manual">Manual</option><option value="automatic">Automatic</option></select></Field>
          </div>
        </section>
        <section className="form-section">
          <h2>Services and rental modes</h2>
          <div className="check-grid">
            <CheckField label="Self-drive" checked={form.self_drive_enabled} onChange={(checked) => update('self_drive_enabled', checked)} />
            <CheckField label="With driver" checked={form.with_driver_enabled} onChange={(checked) => update('with_driver_enabled', checked)} />
            <CheckField label="Hourly rental" checked={form.hourly_rental_enabled} onChange={(checked) => { update('hourly_rental_enabled', checked); if (!checked) update('hourly_base_price', '') }} />
            <CheckField label="Daily rental" checked={form.daily_rental_enabled} onChange={(checked) => { update('daily_rental_enabled', checked); if (!checked) update('daily_base_price', '') }} />
            <CheckField label="Custom trip" checked={form.custom_trip_enabled} onChange={(checked) => update('custom_trip_enabled', checked)} />
          </div>
        </section>
        <section className="form-section">
          <h2>Pricing and availability</h2>
          <div className="vehicle-form-grid">
            {form.hourly_rental_enabled && <Field label="Hourly base price (₹)" id="vehicle-hourly-price"><input id="vehicle-hourly-price" type="number" min="0.01" step="0.01" required value={form.hourly_base_price} onChange={(event) => update('hourly_base_price', event.target.value)} /></Field>}
            {form.daily_rental_enabled && <Field label="Daily base price (₹)" id="vehicle-daily-price"><input id="vehicle-daily-price" type="number" min="0.01" step="0.01" required value={form.daily_base_price} onChange={(event) => update('daily_base_price', event.target.value)} /></Field>}
            <Field label="Advance payment amount (₹)" id="vehicle-advance"><input id="vehicle-advance" type="number" min="0" step="0.01" required value={form.advance_payment_amount} onChange={(event) => update('advance_payment_amount', event.target.value)} /></Field>
            {editing && <Field label="Availability status" id="vehicle-availability"><select id="vehicle-availability" value={form.availability_status} onChange={(event) => update('availability_status', event.target.value as VehicleFormData['availability_status'])}>{form.availability_status === 'inactive' && <option value="inactive">Archived</option>}<option value="available">Available</option><option value="maintenance">Maintenance</option></select></Field>}
          </div>
        </section>
        <section className="form-section">
          <h2>Description and photos</h2>
          <Field label="Description" id="vehicle-description"><textarea id="vehicle-description" rows={4} maxLength={10000} value={form.description} onChange={(event) => update('description', event.target.value)} placeholder="Add helpful details about this vehicle." /></Field>
          <label className="image-dropzone" htmlFor="vehicle-images">
            <CarFront size={22} />
            <span><strong>Select vehicle photos</strong><small>JPEG, PNG, or WebP · up to 8 MB each · 10 files max</small></span>
            <input id="vehicle-images" type="file" accept="image/jpeg,image/png,image/webp" multiple onChange={selectImages} />
          </label>
          {(existingImages.length > 0 || previews.length > 0) && (
            <div className="image-preview-grid">
              {existingImages.map((image) => (
                <div className="image-preview-card" key={image.id}>
                  <img src={apiAssetUrl(image.image_path)} alt="Vehicle" />
                  <div><button type="button" onClick={() => void updateImage(image, { is_primary: true })}>{image.is_primary ? 'Primary photo' : 'Make primary'}</button><button type="button" aria-label="Remove image" onClick={() => void removeImage(image)}><X size={15} /></button></div>
                </div>
              ))}
              {previews.map((preview, index) => <div className="image-preview-card" key={preview}><img src={preview} alt={`Selected vehicle ${index + 1}`} /><button type="button" onClick={() => removeSelectedImage(index)}>Remove</button></div>)}
            </div>
          )}
        </section>
        <div className="vehicle-form-actions">
          <button type="button" className="vehicle-secondary-button" onClick={() => navigate('/admin/vehicles')}>Cancel</button>
          <button type="submit" className="vehicle-primary-button" disabled={busy || categories.length === 0 || cities.length === 0}>
            {busy ? 'Saving…' : editing ? 'Save changes' : 'Save vehicle'} <Check size={16} />
          </button>
        </div>
      </form>
    </AdminLayout>
  )
}

function Field({ label, id, children }: { label: string; id: string; children: ReactNode }) {
  return <div className="vehicle-field"><label htmlFor={id}>{label}</label>{children}</div>
}

function CheckField({ label, checked, onChange }: { label: string; checked: boolean; onChange: (value: boolean) => void }) {
  return <label className="vehicle-check"><input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} /><span>{label}</span></label>
}

type CatalogType = 'cities' | 'categories' | 'pickup-locations'

export function AdminCatalogPage({ type }: { type: CatalogType }) {
  const ready = useAdminGuard()
  const { cities } = useCatalogs()
  const [searchParams] = useSearchParams()
  const [rows, setRows] = useState<Array<City | Category | PickupLocation>>([])
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [busy, setBusy] = useState(false)
  const [editingId, setEditingId] = useState('')
  const [form, setForm] = useState({ name: '', state: '', description: '', city_id: '', address: '', google_maps_url: '' })
  const cityIdFromSearch = searchParams.get('city_id')
  const searchCityKey = `${type}:${cityIdFromSearch ?? ''}`
  const [previousSearchCityKey, setPreviousSearchCityKey] = useState(searchCityKey)
  const title = type === 'cities' ? 'Cities' : type === 'categories' ? 'Categories' : 'Pickup locations'
  const path = `/admin/${type}`

  if (searchCityKey !== previousSearchCityKey) {
    setPreviousSearchCityKey(searchCityKey)
    if (cityIdFromSearch && type === 'pickup-locations') {
      setForm((current) => ({ ...current, city_id: cityIdFromSearch }))
    }
  }

  useEffect(() => {
    if (!ready) return
    apiRequest<Array<City | Category | PickupLocation>>(`${path}?include_inactive=true`)
      .then(setRows)
      .catch((requestError: unknown) => setError(messageFor(requestError)))
  }, [ready, path])

  function edit(row: City | Category | PickupLocation) {
    setEditingId(row.id)
    if (type === 'cities') {
      const city = row as City
      setForm({ name: city.name, state: city.state, description: '', city_id: '', address: '', google_maps_url: '' })
    } else if (type === 'categories') {
      const category = row as Category
      setForm({ name: category.name, state: '', description: category.description ?? '', city_id: '', address: '', google_maps_url: '' })
    } else {
      const location = row as PickupLocation
      setForm({ name: location.name, state: '', description: '', city_id: location.city_id, address: location.address, google_maps_url: location.google_maps_url ?? '' })
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusy(true)
    setError('')
    setSuccess('')
    const payload = type === 'cities'
      ? { name: form.name, state: form.state }
      : type === 'categories'
        ? { name: form.name, description: form.description || null }
        : { name: form.name, city_id: form.city_id, address: form.address, google_maps_url: form.google_maps_url || null }
    try {
      const route = editingId ? `${path}/${editingId}` : path
      const saved = await apiRequest<City | Category | PickupLocation>(route, {
        method: editingId ? 'PATCH' : 'POST',
        body: JSON.stringify(payload),
      })
      setRows((current) => {
        const updated = editingId
          ? current.map((row) => row.id === saved.id ? saved : row)
          : [...current, saved]
        return updated.sort((left, right) => left.name.localeCompare(right.name))
      })
      setSuccess(`${title.slice(0, -1)} ${editingId ? 'updated' : 'created'}.`)
      setEditingId('')
      setForm({ name: '', state: '', description: '', city_id: '', address: '', google_maps_url: '' })
    } catch (requestError) {
      setError(messageFor(requestError))
    } finally {
      setBusy(false)
    }
  }

  async function deactivate(row: City | Category | PickupLocation) {
    if (!window.confirm(`Deactivate ${row.name}?`)) return
    setError('')
    try {
      const updated = await apiRequest<City | Category | PickupLocation>(`${path}/${row.id}`, { method: 'DELETE' })
      setRows((current) => current.map((item) => item.id === row.id ? updated : item))
      setSuccess(`${row.name} was deactivated.`)
    } catch (requestError) {
      setError(messageFor(requestError))
    }
  }

  async function activate(row: City | Category | PickupLocation) {
    setError('')
    setSuccess('')
    try {
      const updated = await apiRequest<City | Category | PickupLocation>(
        `${path}/${row.id}/activate`,
        { method: 'POST' },
      )
      setRows((current) => current.map((item) => item.id === row.id ? updated : item))
      setSuccess(`${row.name} was activated.`)
    } catch (requestError) {
      setError(messageFor(requestError))
    }
  }

  if (!ready) return <p className="vehicle-loading">Checking admin session…</p>
  return (
    <AdminLayout active={path} title={title} description={`Create and maintain fleet ${type.replace('-', ' ')}.`}>
      <Notice error={error} success={success} />
      <div className="catalog-layout">
        <form className="catalog-form" onSubmit={(event) => void submit(event)}>
          <h2>{editingId ? 'Edit' : 'Add'} {type === 'pickup-locations' ? 'pickup location' : type.slice(0, -1)}</h2>
          <Field label={type === 'cities' ? 'City name' : type === 'categories' ? 'Category name' : 'Location name'} id="catalog-name">
            <input id="catalog-name" required minLength={2} maxLength={150} value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} />
          </Field>
          {type === 'cities' && <Field label="State" id="catalog-state"><input id="catalog-state" required value={form.state} onChange={(event) => setForm({ ...form, state: event.target.value })} /></Field>}
          {type === 'categories' && <Field label="Description" id="catalog-description"><textarea id="catalog-description" rows={3} value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></Field>}
          {type === 'pickup-locations' && <>
            <Field label="City" id="catalog-city"><select id="catalog-city" required value={form.city_id} onChange={(event) => setForm({ ...form, city_id: event.target.value })}><option value="">Select city</option>{cities.map((city) => <option key={city.id} value={city.id}>{city.name}</option>)}</select></Field>
            <Field label="Full address" id="catalog-address"><textarea id="catalog-address" rows={3} required value={form.address} onChange={(event) => setForm({ ...form, address: event.target.value })} /></Field>
            <Field label="Google Maps link (optional)" id="catalog-map"><input id="catalog-map" type="url" value={form.google_maps_url} onChange={(event) => setForm({ ...form, google_maps_url: event.target.value })} /></Field>
          </>}
          <div className="catalog-form-actions">
            {editingId && <button type="button" className="vehicle-secondary-button" onClick={() => { setEditingId(''); setForm({ name: '', state: '', description: '', city_id: '', address: '', google_maps_url: '' }) }}>Cancel edit</button>}
            <button type="submit" className="vehicle-primary-button" disabled={busy}>{busy ? 'Saving…' : editingId ? 'Save changes' : 'Create'} <Check size={15} /></button>
          </div>
        </form>
        <div className="catalog-list">
          {rows.map((row) => {
            const active = row.is_active
            const detail = 'state' in row ? row.state : 'city_name' in row ? `${row.city_name} · ${row.address}` : row.description
            return <article className="catalog-row" key={row.id}>
              <div><strong>{row.name}</strong><small>{detail || (active ? 'Active' : 'Inactive')}</small></div>
              <span className={`vehicle-status ${active ? 'available' : 'inactive'}`}>{active ? 'active' : 'inactive'}</span>
              <button type="button" className="table-action" onClick={() => edit(row)}>Edit</button>
              {active && <button type="button" className="table-action danger" onClick={() => void deactivate(row)}>Deactivate</button>}
              {!active && <button type="button" className="table-action" onClick={() => void activate(row)}>Activate</button>}
            </article>
          })}
          {rows.length === 0 && <p className="catalog-empty">No entries yet.</p>}
        </div>
      </div>
    </AdminLayout>
  )
}

export function PublicVehicleListPage() {
  const location = useLocation()
  const [searchParams, setSearchParams] = useSearchParams()
  const registrationNotice = (location.state as { notice?: unknown } | null)?.notice
  const [cities, setCities] = useState<City[]>([])
  const [categories, setCategories] = useState<Category[]>([])
  const [vehicles, setVehicles] = useState<Vehicle[]>([])
  const [error, setError] = useState('')
  const city = searchParams.get('city') ?? ''
  const category = searchParams.get('category') ?? ''
  const selfDrive = searchParams.get('self_drive') ?? ''
  const withDriver = searchParams.get('with_driver') ?? ''
  const fuel = searchParams.get('fuel_type') ?? ''
  const transmission = searchParams.get('transmission') ?? ''
  const params = new URLSearchParams()
  if (city) params.set('city', city)
  if (category) params.set('category', category)
  if (selfDrive) params.set('self_drive', selfDrive)
  if (withDriver) params.set('with_driver', withDriver)
  if (fuel) params.set('fuel_type', fuel)
  if (transmission) params.set('transmission', transmission)
  const vehicleFilterKey = params.toString()
  const [loadedVehicleFilterKey, setLoadedVehicleFilterKey] = useState<string | null>(null)
  const loading = loadedVehicleFilterKey !== vehicleFilterKey

  useEffect(() => {
    Promise.all([apiRequest<City[]>('/cities'), apiRequest<Category[]>('/categories')])
      .then(([cityRows, categoryRows]) => {
        setCities(cityRows)
        setCategories(categoryRows)
      })
      .catch((requestError: unknown) => setError(messageFor(requestError)))
  }, [])

  useEffect(() => {
    let active = true
    apiRequest<Vehicle[]>(`/vehicles?${vehicleFilterKey}`)
      .then((rows) => {
        if (active) setVehicles(rows)
      })
      .catch((requestError: unknown) => {
        if (active) setError(messageFor(requestError))
      })
      .finally(() => {
        if (active) setLoadedVehicleFilterKey(vehicleFilterKey)
      })
    return () => {
      active = false
    }
  }, [vehicleFilterKey])

  function updateFilter(key: string, value: string) {
    const updated = new URLSearchParams(searchParams)
    if (value) updated.set(key, value)
    else updated.delete(key)
    setSearchParams(updated, { replace: true })
  }

  return (
    <main className="public-vehicles-page">
      <CustomerSiteHeader />
      <section className="public-vehicles-hero">
        <div className="public-hero-copy">
          <p className="vehicle-kicker">YOUR NEXT JOURNEY</p>
          <h1>Find a ride that<br /><em>fits your plans.</em></h1>
          <p>From nimble city rides to room for the whole crew, explore vehicles for the way you travel.</p>
        </div>
        <div className="public-hero-visual" aria-hidden="true">
          <VehicleArtwork alt="" categoryName="Car" className="public-hero-car" loading="eager" />
          <VehicleArtwork alt="" categoryName="Bike" className="public-hero-bike" loading="eager" />
          <span className="public-hero-visual-note">CARS <i /> BIKES <i /> MORE</span>
        </div>
      </section>
      <section className="public-vehicle-browser">
        {typeof registrationNotice === 'string' && <Notice error="" success={registrationNotice} />}
        <div className="public-filter-panel">
          <label>City<select value={city} onChange={(event) => updateFilter('city', event.target.value)}><option value="">All cities</option>{cities.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          <label>Category<select value={category} onChange={(event) => updateFilter('category', event.target.value)}><option value="">All categories</option>{categories.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
          <label>Fuel<select value={fuel} onChange={(event) => updateFilter('fuel_type', event.target.value)}><option value="">Any fuel</option>{['petrol', 'diesel', 'cng', 'electric', 'hybrid'].map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
          <label>Transmission<select value={transmission} onChange={(event) => updateFilter('transmission', event.target.value)}><option value="">Any type</option><option value="manual">Manual</option><option value="automatic">Automatic</option></select></label>
          <label className="public-check"><input type="checkbox" checked={selfDrive === 'true'} onChange={(event) => updateFilter('self_drive', event.target.checked ? 'true' : '')} /> Self-drive</label>
          <label className="public-check"><input type="checkbox" checked={withDriver === 'true'} onChange={(event) => updateFilter('with_driver', event.target.checked ? 'true' : '')} /> With driver</label>
        </div>
        <Notice error={error} success="" />
        {loading ? <p className="vehicle-loading">Finding available vehicles…</p> : vehicles.length ? (
          <div className="public-vehicle-grid">{vehicles.map((vehicle) => <PublicVehicleCard key={vehicle.id} vehicle={vehicle} />)}</div>
        ) : <div className="public-empty"><CarFront size={30} /><h2>No vehicles available for these filters.</h2><p>Try another city or adjust your filters.</p></div>}
      </section>
      <footer className="public-vehicles-footer">© 2026 Laxmi Narasimha Rentals · Good journeys, made personal.</footer>
    </main>
  )
}

function PublicVehicleCard({ vehicle }: { vehicle: Vehicle }) {
  const primaryImage = vehicle.images.find((image) => image.is_primary) ?? vehicle.images[0]
  return (
    <article className="public-vehicle-card">
      <Link to={`/vehicles/${vehicle.id}`} className="public-vehicle-photo">
        <VehicleArtwork
          alt={`${vehicle.brand} ${vehicle.model}`}
          categoryName={vehicle.category_name}
          className="public-card-artwork"
          imageUrl={primaryImage ? apiAssetUrl(primaryImage.image_path) : undefined}
        />
        <span className="public-availability">{vehicle.availability_status}</span>
      </Link>
      <div className="public-vehicle-card-body">
        <div className="public-card-title"><div><span>{vehicle.category_name} · {vehicle.city_name}</span><h2>{vehicle.brand} {vehicle.model}</h2></div><Link aria-label={`View ${vehicle.brand} ${vehicle.model}`} to={`/vehicles/${vehicle.id}`}><ArrowRight size={17} /></Link></div>
        <div className="public-specs"><span><Users size={15} /> {vehicle.seating_capacity} seats</span><span><Fuel size={15} /> {vehicle.fuel_type}</span><span><Settings2 size={15} /> {vehicle.transmission_type}</span></div>
        <div className="public-tags">{vehicle.self_drive_enabled && <span>Self-drive</span>}{vehicle.with_driver_enabled && <span>With driver</span>}</div>
        <div className="public-prices">
          {vehicle.hourly_rental_enabled && <strong>₹{vehicle.hourly_base_price}<small>/ hour</small></strong>}
          {vehicle.daily_rental_enabled && <strong>₹{vehicle.daily_base_price}<small>/ day</small></strong>}
        </div>
        <Link className="vehicle-primary-button public-book-link" to={`/vehicles/${vehicle.id}/book`}>Request booking <ArrowRight size={15} /></Link>
      </div>
    </article>
  )
}

export function PublicVehicleDetailPage() {
  const { vehicleId } = useParams()
  const [vehicle, setVehicle] = useState<Vehicle | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!vehicleId) return
    apiRequest<Vehicle>(`/vehicles/${vehicleId}`)
      .then(setVehicle)
      .catch((requestError: unknown) => setError(messageFor(requestError)))
  }, [vehicleId])

  return (
    <main className="public-vehicles-page">
      <CustomerSiteHeader />
      {error ? <section className="public-empty"><h1>Vehicle not found</h1><p>{error}</p><Link className="vehicle-primary-button" to="/vehicles">Browse vehicles</Link></section> : !vehicle ? <p className="vehicle-loading">Loading vehicle details…</p> : (
        <section className="vehicle-detail">
          <Link className="vehicle-back-link" to="/vehicles"><ArrowLeft size={16} /> Back to vehicles</Link>
          <div className="vehicle-detail-heading"><div><p className="vehicle-kicker">{vehicle.category_name} · {vehicle.city_name}</p><h1>{vehicle.brand} {vehicle.model} {vehicle.variant}</h1><p>{vehicle.manufacturing_year} · {vehicle.registration_number}</p></div><span className={`vehicle-status ${vehicle.availability_status}`}>{vehicle.availability_status}</span></div>
          <div className="vehicle-detail-gallery">{vehicle.images.length ? vehicle.images.map((image) => <img key={image.id} src={apiAssetUrl(image.image_path)} alt={`${vehicle.brand} ${vehicle.model}`} />) : <VehicleArtwork alt={`${vehicle.category_name} image unavailable`} categoryName={vehicle.category_name} className="vehicle-photo-placeholder" />}</div>
          <div className="vehicle-detail-grid"><section><h2>Vehicle information</h2><p>{vehicle.description || 'A well-maintained vehicle for your next journey.'}</p><div className="public-specs detail-specs"><span><Users size={16} /> {vehicle.seating_capacity} seats</span><span><Fuel size={16} /> {vehicle.fuel_type}</span><span><Settings2 size={16} /> {vehicle.transmission_type}</span></div><div className="public-tags">{vehicle.self_drive_enabled && <span>Self-drive</span>}{vehicle.with_driver_enabled && <span>With driver</span>}{vehicle.custom_trip_enabled && <span>Custom trips</span>}</div></section><aside><h2>Rental rates</h2>{vehicle.hourly_rental_enabled && <p><span>Hourly</span><strong>₹{vehicle.hourly_base_price} / hour</strong></p>}{vehicle.daily_rental_enabled && <p><span>Daily</span><strong>₹{vehicle.daily_base_price} / day</strong></p>}<p><span>Advance payment</span><strong>₹{vehicle.advance_payment_amount}</strong></p><p><MapPin size={15} /> {vehicle.pickup_location_name}, {vehicle.city_name}</p><Link className="vehicle-primary-button" to={`/vehicles/${vehicle.id}/book`}>Request booking <ArrowRight size={16} /></Link></aside></div>
        </section>
      )}
      <footer className="public-vehicles-footer">© 2026 Laxmi Narasimha Rentals</footer>
    </main>
  )
}
