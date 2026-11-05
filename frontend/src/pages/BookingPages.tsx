import { type FormEvent, useEffect, useMemo, useState } from 'react'
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { ArrowLeft, ArrowRight, Bell, CalendarDays, Check, Clock3, MapPin, ShieldCheck } from 'lucide-react'
import { apiAssetUrl, apiRequest, ApiError } from '../services/api'
import { CustomerSiteHeader } from '../components/CustomerSiteHeader'
import { VehicleArtwork } from '../components/VehicleArtwork'
import { bookingWhatsAppUrl } from '../utils/whatsapp'
import { businessDateTimeToUtc, defaultBusinessDateTime } from '../utils/businessDateTime'

interface Vehicle {
  id: string
  vehicle_code: string
  brand: string
  model: string
  city_id: string
  city_name: string
  pickup_location_id: string
  pickup_location_name: string
  pickup_address: string
  self_drive_enabled: boolean
  with_driver_enabled: boolean
  hourly_rental_enabled: boolean
  daily_rental_enabled: boolean
  custom_trip_enabled: boolean
  hourly_base_price: string | null
  daily_base_price: string | null
  advance_payment_amount: string
  images: Array<{ image_path: string; is_primary: boolean }>
}

interface PickupLocation {
  id: string
  city_id: string
  name: string
  address: string
}

interface Availability {
  available: boolean
  estimated_total: string | null
  advance_amount: string
  hourly_rate: string | null
  daily_rate: string | null
  message: string | null
}

interface AvailabilityResult {
  key: string
  value: Availability
}

interface Booking {
  id: string
  reference: string
  vehicle_id: string
  vehicle_name: string
  vehicle_code: string
  customer_id: string
  customer_mobile: string
  customer_name: string | null
  city_name: string
  pickup_location_name: string
  pickup_address: string
  start_at: string
  end_at: string
  rental_type: string
  driving_mode: string
  estimated_total: string | null
  advance_amount: string
  amount_paid: string
  remaining_balance: string
  status: string
  payment_status: string
  confirmation_method: string | null
  customer_notes: string | null
  admin_notes: string | null
  custom_trip_details: string | null
  licence_verification_status: string
  confirmation_note: string | null
  confirmed_at: string | null
  events?: Array<{ id: string; action: string; note: string | null; created_at: string }>
  payments?: Array<{
    id: string
    amount: string
    payment_method: string
    status: string
    provider: string | null
    provider_reference: string | null
    reference_note: string | null
    notes: string | null
    paid_at: string | null
  }>
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : 'The request could not be completed. Please try again.'
}

function defaultStart(): string {
  return defaultBusinessDateTime(1, 10)
}

function defaultEnd(): string {
  return defaultBusinessDateTime(2, 10)
}

function money(value: string | null | undefined): string {
  if (value == null) return 'Quoted by our team'
  return `₹${Number(value).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`
}

export function CustomerBookingPage() {
  const { vehicleId = '' } = useParams()
  const [vehicle, setVehicle] = useState<Vehicle | null>(null)
  const [pickupLocations, setPickupLocations] = useState<PickupLocation[]>([])
  const [pickupLocationId, setPickupLocationId] = useState('')
  const [startAt, setStartAt] = useState(defaultStart)
  const [endAt, setEndAt] = useState(defaultEnd)
  const [rentalType, setRentalType] = useState('daily')
  const [drivingMode, setDrivingMode] = useState('self_drive')
  const [tripDetails, setTripDetails] = useState('')
  const [customerNotes, setCustomerNotes] = useState('')
  const [availabilityResult, setAvailabilityResult] = useState<AvailabilityResult | null>(null)
  const [availabilityFailure, setAvailabilityFailure] = useState<{ key: string; message: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [currentTime, setCurrentTime] = useState(0)
  const [createdBooking, setCreatedBooking] = useState<Booking | null>(null)
  const availabilityKey = `${vehicle?.id ?? ''}|${pickupLocationId}|${startAt}|${endAt}|${rentalType}|${drivingMode}`
  const availability = availabilityResult?.key === availabilityKey ? availabilityResult.value : null
  const availabilityError = availabilityFailure?.key === availabilityKey
    ? availabilityFailure.message
    : null
  const periodIsValid = (() => {
    try {
      const start = Date.parse(businessDateTimeToUtc(startAt))
      const end = Date.parse(businessDateTimeToUtc(endAt))
      return start > currentTime && end > start
    } catch {
      return false
    }
  })()

  useEffect(() => {
    const updateCurrentTime = () => setCurrentTime(Date.now())
    updateCurrentTime()
    const interval = window.setInterval(updateCurrentTime, 30_000)
    return () => window.clearInterval(interval)
  }, [])

  useEffect(() => {
    let active = true
    apiRequest<Vehicle>(`/vehicles/${vehicleId}`)
      .then((result) => {
        if (!active) return
        setVehicle(result)
        setPickupLocationId(result.pickup_location_id)
        setRentalType(result.daily_rental_enabled ? 'daily' : result.hourly_rental_enabled ? 'hourly' : 'custom_trip')
        setDrivingMode(result.self_drive_enabled ? 'self_drive' : 'with_driver')
        apiRequest<PickupLocation[]>(`/pickup-locations?city=${encodeURIComponent(result.city_id)}`)
          .then((locations) => {
            if (active) setPickupLocations(locations)
          })
          .catch((requestError: unknown) => {
            if (active) setError(errorText(requestError))
          })
      })
      .catch((requestError: unknown) => {
        if (active) setError(errorText(requestError))
      })
    return () => { active = false }
  }, [vehicleId])

  useEffect(() => {
    if (!vehicle || !pickupLocationId || !periodIsValid) {
      return
    }
    let active = true
    const controller = new AbortController()
    const requestKey = `${vehicle.id}|${pickupLocationId}|${startAt}|${endAt}|${rentalType}|${drivingMode}`
    const params = new URLSearchParams({
      start_at: businessDateTimeToUtc(startAt),
      end_at: businessDateTimeToUtc(endAt),
      rental_type: rentalType,
      driving_mode: drivingMode,
      pickup_location_id: pickupLocationId,
    })
    const timeout = window.setTimeout(() => {
      apiRequest<Availability>(`/vehicles/${vehicle.id}/availability?${params}`, {
        signal: controller.signal,
      })
        .then((result) => { if (active) setAvailabilityResult({ key: requestKey, value: result }) })
        .catch((requestError: unknown) => {
          if (active && !(requestError instanceof Error && requestError.name === 'AbortError')) {
            setAvailabilityFailure({ key: requestKey, message: errorText(requestError) })
          }
        })
    }, 300)
    return () => {
      active = false
      window.clearTimeout(timeout)
      controller.abort()
    }
  }, [vehicle, pickupLocationId, startAt, endAt, rentalType, drivingMode, periodIsValid])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!availability?.available) {
      setError('Check that your selected dates and times are available before submitting.')
      return
    }
    setBusy(true)
    setError('')
    try {
      const booking = await apiRequest<Booking>('/bookings', {
        method: 'POST',
        body: JSON.stringify({
          vehicle_id: vehicleId,
          pickup_location_id: pickupLocationId,
          start_at: businessDateTimeToUtc(startAt),
          end_at: businessDateTimeToUtc(endAt),
          rental_type: rentalType,
          driving_mode: drivingMode,
          custom_trip_details: tripDetails || null,
          customer_notes: customerNotes || null,
        }),
      })
      window.dispatchEvent(new Event('lnr-notifications-updated'))
      setCreatedBooking(booking)
    } catch (requestError) {
      if (requestError instanceof ApiError && requestError.status === 409) {
        const message = 'This vehicle is unavailable for your selected dates and times.'
        setAvailabilityResult({
          key: availabilityKey,
          value: {
            available: false,
            estimated_total: null,
            advance_amount: vehicle?.advance_payment_amount ?? '0',
            hourly_rate: vehicle?.hourly_base_price ?? null,
            daily_rate: vehicle?.daily_base_price ?? null,
            message,
          },
        })
        setError(`${message} Please select another period.`)
      } else {
        setError(errorText(requestError))
      }
    } finally {
      setBusy(false)
    }
  }

  if (createdBooking) {
    return (
      <main className="booking-page">
        <CustomerSiteHeader />
        <section className="booking-confirmation">
          <span className="booking-confirm-icon"><Check size={26} /></span>
          <p className="vehicle-kicker">REQUEST RECEIVED</p>
          <h1>Your journey is<br /><em>one step closer.</em></h1>
          <p>Booking reference <strong>{createdBooking.reference}</strong>. Your request is pending confirmation. The vehicle is not reserved until confirmed.</p>
          <p>Online advance payment is coming soon. Contact our team to arrange confirmation and payment.</p>
          <div className="booking-confirm-actions"><Link className="vehicle-primary-button" to="/bookings">View my bookings <ArrowRight size={16} /></Link><Link className="vehicle-secondary-button" to="/vehicles">Browse vehicles</Link></div>
        </section>
      </main>
    )
  }

  return (
    <main className="booking-page">
      <CustomerSiteHeader />
      <section className="booking-shell">
        <Link className="vehicle-back-link" to={`/vehicles/${vehicleId}`}><ArrowLeft size={15} /> Back to vehicle</Link>
        <p className="vehicle-kicker">BOOKING REQUEST</p>
        <h1>Plan your <em>journey.</em></h1>
        {error && <p className="vehicle-notice error" role="alert">{error}</p>}
        {!vehicle ? <p className="vehicle-loading">Loading vehicle…</p> : (
          <div className="booking-grid">
            <section className="booking-vehicle-card">
              <VehicleArtwork
                alt={`${vehicle.brand} ${vehicle.model}`}
                categoryName="Vehicle"
                className="booking-vehicle-artwork"
                imageUrl={vehicle.images.length > 0
                  ? apiAssetUrl(vehicle.images.find((image) => image.is_primary)?.image_path ?? vehicle.images[0].image_path)
                  : undefined}
              />
              <span className="vehicle-kicker">{vehicle.vehicle_code} · {vehicle.city_name}</span>
              <h2>{vehicle.brand} {vehicle.model}</h2>
              <p><MapPin size={15} /> {pickupLocations.find((item) => item.id === pickupLocationId)?.name ?? vehicle.pickup_location_name}, {pickupLocations.find((item) => item.id === pickupLocationId)?.address ?? vehicle.pickup_address}</p>
              <p className="booking-return-note">Pickup and return are at the selected location.</p>
              <p><ShieldCheck size={15} /> Advance configured for this vehicle: <strong>{money(vehicle.advance_payment_amount)}</strong></p>
            </section>
            <form className="booking-form" onSubmit={(event) => void submit(event)}>
              <div className="booking-form-grid">
                <label>Pick-up location<select required value={pickupLocationId} onChange={(event) => setPickupLocationId(event.target.value)}>{pickupLocations.map((item) => <option key={item.id} value={item.id}>{item.name} — {item.address}</option>)}</select></label>
                <label>Pick-up date & time<input type="datetime-local" required value={startAt} onChange={(event) => setStartAt(event.target.value)} /></label>
                <label>Return date & time<input type="datetime-local" required value={endAt} onChange={(event) => setEndAt(event.target.value)} /></label>
                <label>Rental type<select value={rentalType} onChange={(event) => setRentalType(event.target.value)}>
                  {vehicle.hourly_rental_enabled && <option value="hourly">Hourly</option>}
                  {vehicle.daily_rental_enabled && <option value="daily">Daily</option>}
                  {vehicle.custom_trip_enabled && <option value="custom_trip">Custom trip · quotation</option>}
                </select></label>
                <label>Driving mode<select value={drivingMode} onChange={(event) => setDrivingMode(event.target.value)}>
                  {vehicle.self_drive_enabled && <option value="self_drive">Self-drive</option>}
                  {vehicle.with_driver_enabled && <option value="with_driver">With driver</option>}
                </select></label>
              </div>
              {rentalType === 'custom_trip' && <label>Trip details<textarea required rows={3} value={tripDetails} onChange={(event) => setTripDetails(event.target.value)} placeholder="Tell us your destination, duration, and plans." /></label>}
              <label>Notes for our team<textarea rows={3} maxLength={4000} value={customerNotes} onChange={(event) => setCustomerNotes(event.target.value)} /></label>
              {drivingMode === 'self_drive' && <p className="booking-info">Licence verification will be arranged privately with the admin. No licence documents are uploaded on this page.</p>}
              <div className="booking-estimate" aria-live="polite">
                <div><span>Estimated rental</span><strong>{rentalType === 'custom_trip' ? 'Admin quotation required' : availability ? money(availability.estimated_total) : 'Checking availability…'}</strong></div>
                <div><span>Required advance</span><strong>{money(availability?.advance_amount ?? vehicle.advance_payment_amount)}</strong></div>
                <p>{availability?.available === false
                  ? 'This vehicle is unavailable for your selected dates and times.'
                  : availabilityError
                    ? `We could not verify availability: ${availabilityError}`
                    : !periodIsValid
                      ? 'Choose a future pickup time and a later return time. Times use India Standard Time.'
                      : availability?.message ?? 'Checking current availability. A pending request does not reserve the vehicle.'}</p>
              </div>
              <div className="booking-payment-option"><strong>Online advance payment</strong><span>Coming soon. No payment is taken in this phase.</span></div>
              <button className="vehicle-primary-button" type="submit" disabled={busy || !periodIsValid || !availability || !availability.available}>
                {busy
                  ? 'Submitting request…'
                  : availability?.available === false
                    ? 'Unavailable'
                    : availabilityError
                      ? 'Availability check failed'
                      : !availability
                        ? periodIsValid ? 'Checking availability…' : 'Select valid times'
                        : 'Submit Request'} <ArrowRight size={16} />
              </button>
            </form>
          </div>
        )}
      </section>
    </main>
  )
}

export function CustomerBookingHistoryPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const [bookings, setBookings] = useState<Booking[]>([])
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState('')

  useEffect(() => {
    let active = true
    apiRequest<Booking[]>('/bookings/me')
      .then((rows) => { if (active) setBookings(rows) })
      .catch((requestError: unknown) => {
        if (active) navigate(requestError instanceof ApiError && requestError.status === 401
          ? `/login?next=${encodeURIComponent(`${location.pathname}${location.search}`)}`
          : '/unauthorized', { replace: true })
      })
    return () => { active = false }
  }, [navigate, location.pathname, location.search])

  useEffect(() => {
    const bookingId = searchParams.get('booking')
    if (bookingId && bookings.length > 0) {
      document.getElementById(`booking-${bookingId}`)?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [bookings, searchParams])

  async function cancel(bookingId: string) {
    setBusyId(bookingId)
    setError('')
    try {
      const updated = await apiRequest<Booking>(`/bookings/${bookingId}/cancel`, {
        method: 'POST',
        body: JSON.stringify({ note: 'Cancelled by customer.' }),
      })
      setBookings((current) => current.map((booking) => booking.id === updated.id ? updated : booking))
      window.dispatchEvent(new Event('lnr-notifications-updated'))
    } catch (requestError) {
      setError(errorText(requestError))
    } finally {
      setBusyId('')
    }
  }

  return (
    <main className="booking-page">
      <CustomerSiteHeader />
      <section className="booking-shell">
        <p className="vehicle-kicker">YOUR JOURNEYS</p>
        <h1>My <em>bookings.</em></h1>
        {error && <p className="vehicle-notice error" role="alert">{error}</p>}
        <div className="booking-list">
          {bookings.map((booking) => (
            <article className="booking-list-card" id={`booking-${booking.id}`} key={booking.id}>
              <div className="booking-list-title"><div><span className="vehicle-kicker">{booking.reference}</span><h2>{booking.vehicle_name}</h2></div><span className={`vehicle-status ${booking.status}`}>{booking.status.replace('_', ' ')}</span></div>
              <p><CalendarDays size={15} /> {new Date(booking.start_at).toLocaleString()} — {new Date(booking.end_at).toLocaleString()}</p>
              <p><MapPin size={15} /> Pickup & return: {booking.pickup_location_name}, {booking.pickup_address}</p>
              <div className="booking-list-money"><span>Estimate {money(booking.estimated_total)}</span><span>Advance {money(booking.advance_amount)} · {booking.payment_status.replace('_', ' ')}</span></div>
              <p>Paid {money(booking.amount_paid)} · Remaining balance {money(booking.remaining_balance)}</p>
              {booking.status === 'pending' && <button className="vehicle-secondary-button" type="button" disabled={busyId === booking.id} onClick={() => void cancel(booking.id)}>{busyId === booking.id ? 'Cancelling…' : 'Cancel request'}</button>}
              <small>Online payment: coming soon. Contact the admin to arrange confirmation.</small>
            </article>
          ))}
          {bookings.length === 0 && <div className="public-empty"><Clock3 size={28} /><h2>No bookings yet</h2><p>Your booking requests will appear here.</p><Link className="vehicle-primary-button" to="/vehicles">Browse vehicles</Link></div>}
        </div>
      </section>
    </main>
  )
}

interface CustomerNotification {
  id: string
  booking_id: string
  booking_reference: string
  title: string
  message: string
  read_at: string | null
  created_at: string
}

export function CustomerNotificationsPage() {
  const navigate = useNavigate()
  const [notifications, setNotifications] = useState<CustomerNotification[]>([])
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    apiRequest<CustomerNotification[]>('/notifications')
      .then((rows) => { if (active) setNotifications(rows) })
      .catch((requestError: unknown) => {
        if (active) navigate(requestError instanceof ApiError && requestError.status === 401
          ? `/login?next=${encodeURIComponent('/notifications')}`
          : '/unauthorized', { replace: true })
      })
    return () => { active = false }
  }, [navigate])

  async function openNotification(notification: CustomerNotification) {
    setError('')
    try {
      if (!notification.read_at) {
        const updated = await apiRequest<CustomerNotification>(
          `/notifications/${notification.id}/read`,
          { method: 'POST', body: JSON.stringify({}) },
        )
        setNotifications((current) => current.map((item) => item.id === updated.id ? updated : item))
      }
      navigate(`/bookings?booking=${encodeURIComponent(notification.booking_id)}`)
    } catch (requestError) {
      setError(errorText(requestError))
    }
  }

  return (
    <main className="booking-page">
      <CustomerSiteHeader />
      <section className="booking-shell">
        <p className="vehicle-kicker">ACCOUNT UPDATES</p>
        <h1>Notifications.</h1>
        {error && <p className="vehicle-notice error" role="alert">{error}</p>}
        <div className="booking-list">
          {notifications.map((notification) => (
            <article className="booking-list-card" key={notification.id}>
              <div className="booking-list-title">
                <div><span className="vehicle-kicker">{notification.booking_reference}</span><h2>{notification.title}</h2></div>
                {!notification.read_at && <span className="vehicle-status pending">Unread</span>}
              </div>
              <p>{notification.message}</p>
              <small>{new Date(notification.created_at).toLocaleString()}</small>
              <button className="vehicle-secondary-button" type="button" onClick={() => void openNotification(notification)}>Open booking</button>
            </article>
          ))}
          {notifications.length === 0 && <div className="public-empty"><Bell size={28} /><h2>No notifications yet</h2><p>Booking updates will remain here after you sign in again.</p></div>}
        </div>
      </section>
    </main>
  )
}

export function AdminBookingsPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [bookings, setBookings] = useState<Booking[]>([])
  const [vehicles, setVehicles] = useState<Vehicle[]>([])
  const [filter, setFilter] = useState('pending')
  const [search, setSearch] = useState('')
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState('')
  const [notes, setNotes] = useState<Record<string, string>>({})
  const [advanceAmounts, setAdvanceAmounts] = useState<Record<string, string>>({})
  const [paymentMethods, setPaymentMethods] = useState<Record<string, string>>({})
  const [paymentDates, setPaymentDates] = useState<Record<string, string>>({})
  const [paymentReferences, setPaymentReferences] = useState<Record<string, string>>({})
  const [paymentNotes, setPaymentNotes] = useState<Record<string, string>>({})
  const [quotationAmounts, setQuotationAmounts] = useState<Record<string, string>>({})
  const [internalNotes, setInternalNotes] = useState<Record<string, string>>({})
  const [expandedBookingId, setExpandedBookingId] = useState('')
  const [detailsBusyId, setDetailsBusyId] = useState('')
  const [manual, setManual] = useState({
    mobile: '',
    vehicle_id: searchParams.get('vehicle_id') ?? '',
    start_at: defaultStart(),
    end_at: defaultEnd(),
    rental_type: 'daily',
    driving_mode: 'self_drive',
    custom_trip_details: '',
    confirmation_note: '',
  })

  useEffect(() => {
    let active = true
    const params = new URLSearchParams()
    if (filter) params.set('status', filter)
    if (search.trim()) params.set('search', search.trim())
    const query = params.toString()
    apiRequest<Booking[]>(`/admin/bookings${query ? `?${query}` : ''}`)
      .then((rows) => { if (active) setBookings(rows) })
      .catch((requestError: unknown) => {
        if (active) navigate(requestError instanceof ApiError && requestError.status === 401 ? '/session-expired' : '/unauthorized', { replace: true })
      })
    apiRequest<Vehicle[]>('/admin/vehicles?include_inactive=false')
      .then((rows) => { if (active) setVehicles(rows) })
      .catch((requestError: unknown) => { if (active) setError(errorText(requestError)) })
    return () => { active = false }
  }, [filter, navigate, search, searchParams])

  const selectedVehicle = useMemo(() => vehicles.find((vehicle) => vehicle.id === manual.vehicle_id), [vehicles, manual.vehicle_id])

  async function action(booking: Booking, endpoint: string, payload: unknown) {
    setBusyId(booking.id)
    setError('')
    try {
      const updated = await apiRequest<Booking>(`/admin/bookings/${booking.id}/${endpoint}`, {
        method: 'POST',
        body: JSON.stringify(payload),
      })
      setBookings((current) => current.map((item) => item.id === updated.id ? updated : item))
      setExpandedBookingId('')
    } catch (requestError) {
      setError(errorText(requestError))
    } finally {
      setBusyId('')
    }
  }

  async function saveInternalNote(booking: Booking) {
    setBusyId(booking.id)
    setError('')
    try {
      const updated = await apiRequest<Booking>(`/admin/bookings/${booking.id}/notes`, {
        method: 'PATCH',
        body: JSON.stringify({ admin_notes: internalNotes[booking.id] ?? booking.admin_notes ?? null }),
      })
      setBookings((current) => current.map((item) => item.id === updated.id ? { ...item, ...updated } : item))
    } catch (requestError) {
      setError(errorText(requestError))
    } finally {
      setBusyId('')
    }
  }

  async function toggleDetails(booking: Booking) {
    if (expandedBookingId === booking.id) {
      setExpandedBookingId('')
      return
    }
    setExpandedBookingId(booking.id)
    if (booking.events && booking.payments) return
    setDetailsBusyId(booking.id)
    setError('')
    try {
      const details = await apiRequest<Booking>(`/admin/bookings/${booking.id}`)
      setBookings((current) => current.map((item) => item.id === details.id ? details : item))
    } catch (requestError) {
      setError(errorText(requestError))
    } finally {
      setDetailsBusyId('')
    }
  }

  async function createManual(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusyId('manual')
    setError('')
    try {
      const booking = await apiRequest<Booking>('/admin/bookings/manual', {
        method: 'POST',
        body: JSON.stringify({
          ...manual,
          start_at: businessDateTimeToUtc(manual.start_at),
          end_at: businessDateTimeToUtc(manual.end_at),
          custom_trip_details: manual.custom_trip_details || null,
          confirmation_note: manual.confirmation_note || null,
        }),
      })
      setBookings((current) => [booking, ...current])
      setFilter('')
    } catch (requestError) {
      setError(errorText(requestError))
    } finally {
      setBusyId('')
    }
  }

  return (
    <main className="vehicle-admin-page">
      <header className="vehicle-admin-header">
        <Link className="brand" to="/"><span className="brand-mark">LN</span><span className="brand-name"><strong>LAXMI NARASIMHA</strong><small>RENTALS</small></span></Link>
        <Link to="/admin" className="vehicle-admin-back"><ArrowLeft size={15} /> Admin dashboard</Link>
      </header>
      <div className="booking-admin-shell">
        <section className="vehicle-page-heading"><div><p className="vehicle-kicker">ADMIN WORKSPACE</p><h1>Booking management</h1><p>Review requests, confirm by hand, and keep an auditable payment trail.</p></div></section>
        {error && <p className="vehicle-notice error" role="alert">{error}</p>}
        <section className="booking-manual-panel">
          <h2>Create a manual booking</h2>
          <p>Bookings created here are checked for availability and confirmed by the admin.</p>
          <form className="booking-form booking-admin-form" onSubmit={(event) => void createManual(event)}>
            <div className="booking-form-grid">
              <label>Customer mobile<input required value={manual.mobile} onChange={(event) => setManual({ ...manual, mobile: event.target.value })} placeholder="+91 98765 43210" /></label>
              <label>Vehicle<select required value={manual.vehicle_id} onChange={(event) => {
                const next = vehicles.find((vehicle) => vehicle.id === event.target.value)
                setManual({ ...manual, vehicle_id: event.target.value, driving_mode: next?.self_drive_enabled ? 'self_drive' : 'with_driver', rental_type: next?.daily_rental_enabled ? 'daily' : next?.hourly_rental_enabled ? 'hourly' : 'custom_trip' })
              }}><option value="">Select vehicle</option>{vehicles.map((vehicle) => <option key={vehicle.id} value={vehicle.id}>{vehicle.brand} {vehicle.model} · {vehicle.city_name}</option>)}</select></label>
              <label>Pick-up<input type="datetime-local" required value={manual.start_at} onChange={(event) => setManual({ ...manual, start_at: event.target.value })} /></label>
              <label>Return<input type="datetime-local" required value={manual.end_at} onChange={(event) => setManual({ ...manual, end_at: event.target.value })} /></label>
              <label>Rental type<select value={manual.rental_type} onChange={(event) => setManual({ ...manual, rental_type: event.target.value })}>
                {selectedVehicle?.hourly_rental_enabled && <option value="hourly">Hourly</option>}
                {selectedVehicle?.daily_rental_enabled && <option value="daily">Daily</option>}
                {selectedVehicle?.custom_trip_enabled && <option value="custom_trip">Custom trip</option>}
              </select></label>
              <label>Driving mode<select value={manual.driving_mode} onChange={(event) => setManual({ ...manual, driving_mode: event.target.value })}>
                {selectedVehicle?.self_drive_enabled && <option value="self_drive">Self-drive</option>}
                {selectedVehicle?.with_driver_enabled && <option value="with_driver">With driver</option>}
              </select></label>
            </div>
            {manual.rental_type === 'custom_trip' && <label>Trip details<textarea required value={manual.custom_trip_details} onChange={(event) => setManual({ ...manual, custom_trip_details: event.target.value })} /></label>}
            <label>Confirmation note<input maxLength={4000} value={manual.confirmation_note} onChange={(event) => setManual({ ...manual, confirmation_note: event.target.value })} /></label>
            <button className="vehicle-primary-button" disabled={busyId === 'manual'}>{busyId === 'manual' ? 'Creating…' : 'Create and confirm'} <Check size={15} /></button>
          </form>
        </section>
        <div className="booking-admin-toolbar">
          <h2>Requests</h2>
          <label>Search bookings<input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Reference, customer, mobile, vehicle" /></label>
          <label>Status filter<select value={filter} onChange={(event) => setFilter(event.target.value)}>
            <option value="">All bookings</option>
            {['pending', 'awaiting_payment', 'confirmed', 'rejected', 'cancelled', 'completed', 'expired'].map((status) => <option key={status} value={status}>{status}</option>)}
          </select></label>
        </div>
        <div className="booking-list">
          {bookings.map((booking) => (
            <article className="booking-list-card" key={booking.id}>
              <div className="booking-list-title"><div><span className="vehicle-kicker">{booking.reference} · {booking.vehicle_code}</span><h2>{booking.vehicle_name}</h2></div><span className={`vehicle-status ${booking.status}`}>{booking.status.replace('_', ' ')}</span></div>
              <p><strong>{booking.customer_name || 'Customer'}</strong> · {booking.customer_mobile}</p>
              <p><CalendarDays size={15} /> {new Date(booking.start_at).toLocaleString()} — {new Date(booking.end_at).toLocaleString()}</p>
              <p><MapPin size={15} /> {booking.city_name} · Pickup & return: {booking.pickup_location_name}, {booking.pickup_address}</p>
              <p>{booking.rental_type.replace('_', ' ')} · {booking.driving_mode.replace('_', ' ')} · Licence: {booking.licence_verification_status}</p>
              {booking.custom_trip_details && <p>Trip details: {booking.custom_trip_details}</p>}
              {booking.customer_notes && <p>Customer note: {booking.customer_notes}</p>}
              <div className="booking-list-money"><span>Estimate {money(booking.estimated_total)}</span><span>Advance {money(booking.advance_amount)} · paid {money(booking.amount_paid)} · {booking.payment_status.replace('_', ' ')}</span></div>
              <div className="booking-internal-notes">
                <label>Internal booking notes<textarea rows={2} maxLength={4000} value={internalNotes[booking.id] ?? booking.admin_notes ?? ''} onChange={(event) => setInternalNotes({ ...internalNotes, [booking.id]: event.target.value })} /></label>
                <button type="button" className="vehicle-secondary-button" disabled={busyId === booking.id} onClick={() => void saveInternalNote(booking)}>{busyId === booking.id ? 'Saving…' : 'Save internal note'}</button>
              </div>
              <div className="booking-admin-actions">
                {bookingWhatsAppUrl({
                  reference: booking.reference,
                  customerName: booking.customer_name,
                  phone: booking.customer_mobile,
                  vehicleName: booking.vehicle_name,
                  startAt: booking.start_at,
                  endAt: booking.end_at,
                  status: booking.status,
                }) && <a className="vehicle-secondary-button" target="_blank" rel="noreferrer" href={bookingWhatsAppUrl({
                  reference: booking.reference,
                  customerName: booking.customer_name,
                  phone: booking.customer_mobile,
                  vehicleName: booking.vehicle_name,
                  startAt: booking.start_at,
                  endAt: booking.end_at,
                  status: booking.status,
                }) ?? undefined}>Open WhatsApp message</a>}
                <small>WhatsApp is opened with a draft; an admin must manually send it.</small>
                {booking.rental_type === 'custom_trip' && ['pending', 'awaiting_payment'].includes(booking.status) && <div className="booking-quotation-action">
                  <label>Custom-trip quotation<input aria-label="Custom-trip quotation" inputMode="decimal" placeholder="Total rental amount" value={quotationAmounts[booking.id] ?? booking.estimated_total ?? ''} onChange={(event) => setQuotationAmounts({ ...quotationAmounts, [booking.id]: event.target.value })} /></label>
                  <button type="button" className="vehicle-secondary-button" disabled={busyId === booking.id || !quotationAmounts[booking.id]} onClick={() => void action(booking, 'quotation', { amount: quotationAmounts[booking.id], note: notes[booking.id] || null })}>Save quotation</button>
                </div>}
                {booking.status === 'pending' && <>
                  <input aria-label="Confirmation note" placeholder="Optional confirmation note" value={notes[booking.id] ?? ''} onChange={(event) => setNotes({ ...notes, [booking.id]: event.target.value })} />
                  <button type="button" className="vehicle-primary-button" disabled={busyId === booking.id} onClick={() => void action(booking, 'confirm', { note: notes[booking.id] || null })}>{busyId === booking.id ? 'Saving…' : 'Confirm manually'}</button>
                  <button type="button" className="vehicle-secondary-button" disabled={busyId === booking.id} onClick={() => {
                    const reason = window.prompt('Reason for rejecting this request')
                    if (reason) void action(booking, 'reject', { note: reason })
                  }}>Reject</button>
                </>}
                {['pending', 'awaiting_payment', 'confirmed'].includes(booking.status) && !['waived', 'offline_paid', 'online_paid'].includes(booking.payment_status) && <>
                  <input aria-label="Offline advance amount" inputMode="decimal" placeholder="Offline advance amount" value={advanceAmounts[booking.id] ?? String(Math.max(0, Number(booking.advance_amount) - Number(booking.amount_paid)))} onChange={(event) => setAdvanceAmounts({ ...advanceAmounts, [booking.id]: event.target.value })} />
                  <select aria-label="Offline payment method" value={paymentMethods[booking.id] ?? 'upi'} onChange={(event) => setPaymentMethods({ ...paymentMethods, [booking.id]: event.target.value })}><option value="upi">UPI</option><option value="cash">Cash</option><option value="bank_transfer">Bank transfer</option></select>
                  <input aria-label="Offline payment received date and time" type="datetime-local" value={paymentDates[booking.id] ?? ''} onChange={(event) => setPaymentDates({ ...paymentDates, [booking.id]: event.target.value })} />
                  <input aria-label="Offline payment reference" placeholder="Payment reference (optional)" value={paymentReferences[booking.id] ?? ''} onChange={(event) => setPaymentReferences({ ...paymentReferences, [booking.id]: event.target.value })} />
                  <input aria-label="Offline payment notes" placeholder="Payment notes (optional)" value={paymentNotes[booking.id] ?? ''} onChange={(event) => setPaymentNotes({ ...paymentNotes, [booking.id]: event.target.value })} />
                  <button type="button" className="vehicle-secondary-button" disabled={busyId === booking.id} onClick={() => void action(booking, 'offline-advance', { amount: advanceAmounts[booking.id] ?? String(Math.max(0, Number(booking.advance_amount) - Number(booking.amount_paid))), payment_method: paymentMethods[booking.id] ?? 'upi', received_at: paymentDates[booking.id] ? businessDateTimeToUtc(paymentDates[booking.id]) : null, reference_note: paymentReferences[booking.id] || null, notes: paymentNotes[booking.id] || null })}>Record offline advance</button>
                  <button type="button" className="vehicle-secondary-button" disabled={busyId === booking.id} onClick={() => {
                    const reason = window.prompt('Reason for waiving the advance')
                    if (reason) void action(booking, 'waive-advance', { reason })
                  }}>Waive advance</button>
                </>}
                {booking.status === 'confirmed' && <>
                  <button type="button" className="vehicle-secondary-button" onClick={() => void action(booking, 'complete', { note: null })}>Mark completed</button>
                  <button type="button" className="vehicle-secondary-button" onClick={() => {
                    const reason = window.prompt('Reason for cancellation')
                    if (reason) void action(booking, 'cancel', { note: reason })
                  }}>Cancel booking</button>
                </>}
              </div>
              <button type="button" className="booking-details-toggle" onClick={() => void toggleDetails(booking)}>{detailsBusyId === booking.id ? 'Loading details…' : expandedBookingId === booking.id ? 'Hide booking details' : 'Booking details & audit'}</button>
              {expandedBookingId === booking.id && <div className="booking-detail-panel">
                <p>Confirmation: {booking.confirmation_method ?? 'Not confirmed'}{booking.confirmed_at ? ` · ${new Date(booking.confirmed_at).toLocaleString()}` : ''}</p>
                <p>Remaining balance: {money(booking.remaining_balance)}</p>
                {booking.payments && booking.payments.length > 0 && <section><h3>Payment records</h3>{booking.payments.map((payment) => <p key={payment.id}>{money(payment.amount)} · {payment.payment_method} · {payment.status}{payment.paid_at ? ` · ${new Date(payment.paid_at).toLocaleString()}` : ''}{payment.reference_note ? ` · Reference: ${payment.reference_note}` : ''}{payment.notes ? ` · Notes: ${payment.notes}` : ''}{payment.provider_reference ? ` · ${payment.provider_reference}` : ''}</p>)}</section>}
                {booking.events && booking.events.length > 0 && <section className="booking-history"><h3>Booking audit history</h3>{booking.events.map((event) => <p key={event.id}>{new Date(event.created_at).toLocaleString()} · {event.action}{event.note ? ` — ${event.note}` : ''}</p>)}</section>}
              </div>}
            </article>
          ))}
          {bookings.length === 0 && <div className="public-empty"><h2>No bookings in this view</h2><p>New customer requests will appear here.</p></div>}
        </div>
      </div>
    </main>
  )
}
