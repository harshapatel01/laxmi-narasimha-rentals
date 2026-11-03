import { Fragment, type ReactNode, useState } from 'react'
import { Link, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import {
  ArrowRight,
  ArrowUpRight,
  CalendarDays,
  Check,
  ChevronDown,
  Clock3,
  Compass,
  MapPin,
  Menu,
  PhoneCall,
  ShieldCheck,
} from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { apiAssetUrl, apiRequest, getApiHealth } from './services/api'
import { CustomerAccountNavigation } from './components/CustomerSiteHeader'
import { VehicleArtwork } from './components/VehicleArtwork'
import { useCustomerSession } from './services/customerSession'
import {
  AdminLoginPage,
  AdminMfaPage,
  CustomerAccountPage,
  CustomerLoginPage,
  CustomerRegistrationPage,
  PasswordResetPage,
  SessionExpiredPage,
  UnauthorizedPage,
} from './pages/AuthPages'
import {
  AdminCatalogPage,
  AdminHomePage,
  AdminVehicleListPage,
  AdminCustomersPage,
  PublicVehicleDetailPage,
  PublicVehicleListPage,
  VehicleFormPage,
} from './pages/VehiclePages'
import {
  AdminBookingsPage,
  CustomerBookingHistoryPage,
  CustomerBookingPage,
  CustomerNotificationsPage,
} from './pages/BookingPages'
import './App.css'
import './pages/AuthPages.css'
import './pages/VehiclePages.css'
import './pages/BookingPages.css'

interface FeaturedVehicle {
  id: string
  brand: string
  model: string
  category_name: string
  city_name: string
  daily_rental_enabled: boolean
  daily_base_price: string | null
  hourly_rental_enabled: boolean
  hourly_base_price: string | null
  images: Array<{ image_path: string; is_primary: boolean }>
}

interface PublicCity {
  id: string
  name: string
}

interface PublicCategory {
  id: string
  name: string
  description: string | null
}

export function HomePage() {
  const customerSession = useCustomerSession()
  const [cityId, setCityId] = useState('')
  const [cityMenuOpen, setCityMenuOpen] = useState(false)
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const location = useLocation()
  const apiHealth = useQuery({
    queryKey: ['api-health'],
    queryFn: getApiHealth,
    retry: false,
    refetchInterval: 30_000,
  })
  const featuredVehicles = useQuery({
    queryKey: ['featured-vehicles', cityId],
    queryFn: () => apiRequest<FeaturedVehicle[]>(
      cityId ? `/vehicles?city=${encodeURIComponent(cityId)}` : '/vehicles',
    ),
    retry: false,
    staleTime: 0,
    refetchOnMount: 'always',
  })
  const publicCities = useQuery({
    queryKey: ['public-cities'],
    queryFn: () => apiRequest<PublicCity[]>('/cities'),
    retry: false,
  })
  const publicCategories = useQuery({
    queryKey: ['public-categories'],
    queryFn: () => apiRequest<PublicCategory[]>('/categories'),
    retry: false,
  })
  const selectedCity = publicCities.data?.find((item) => item.id === cityId)
  const vehicleListUrl = cityId ? `/vehicles?city=${encodeURIComponent(cityId)}` : '/vehicles'
  const registrationNotice = (location.state as { notice?: unknown } | null)?.notice

  return (
    <main>
      {typeof registrationNotice === 'string' && (
        <p className="vehicle-notice success" role="status">{registrationNotice}</p>
      )}
      <div className="announcement">
        <span className="announcement-dot" />
        Your next journey starts right here
        <span className="announcement-divider">·</span>
        Local rentals, made personal
      </div>

      <header className="site-header">
        <Link className="brand" to="/" aria-label="Laxmi Narasimha Rentals home">
          <span className="brand-mark">LN</span>
          <span className="brand-name">
            <strong>LAXMI NARASIMHA</strong>
            <small>RENTALS</small>
          </span>
        </Link>

        <nav id="primary-navigation" className={`main-nav ${mobileMenuOpen ? 'is-open' : ''}`}>
          <a href="#fleet" onClick={() => setMobileMenuOpen(false)}>Vehicle types</a>
          <a href="#how-it-works" onClick={() => setMobileMenuOpen(false)}>How it works</a>
          <a href="#support" onClick={() => setMobileMenuOpen(false)}>Contact</a>
          <CustomerAccountNavigation className="home-account-link" />
        </nav>

        <div className="header-actions">
          <div className="city-picker">
            <button
              className="city-trigger"
              type="button"
              aria-expanded={cityMenuOpen}
              onClick={() => setCityMenuOpen(!cityMenuOpen)}
            >
              <MapPin size={16} />
              <span>{selectedCity?.name ?? 'All cities'}</span>
              <ChevronDown size={15} />
            </button>
            {cityMenuOpen && (
              <div className="city-menu">
                <span className="city-menu-label">Choose your city</span>
                <button
                  className={!cityId ? 'city-option selected' : 'city-option'}
                  type="button"
                  onClick={() => {
                    setCityId('')
                    setCityMenuOpen(false)
                  }}
                >
                  <MapPin size={15} />
                  All cities
                  {!cityId && <Check size={15} />}
                </button>
                {publicCities.data?.map((option) => (
                  <button
                    className={option.id === cityId ? 'city-option selected' : 'city-option'}
                    key={option.id}
                    type="button"
                    onClick={() => {
                      setCityId(option.id)
                      setCityMenuOpen(false)
                    }}
                  >
                    <MapPin size={15} />
                    {option.name}
                    {option.id === cityId && <Check size={15} />}
                  </button>
                ))}
              </div>
            )}
          </div>
          <Link className="button button-dark header-cta" to={vehicleListUrl}>
            Explore vehicles <ArrowUpRight size={16} />
          </Link>
          <button
            className="mobile-menu-button"
            type="button"
            aria-label={mobileMenuOpen ? 'Close menu' : 'Open menu'}
            aria-controls="primary-navigation"
            aria-expanded={mobileMenuOpen}
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
          >
            <Menu size={22} />
          </button>
        </div>
      </header>

      <section className="hero">
        <div className="hero-copy">
          <div className="eyebrow"><span /> LOCAL RENTALS, MADE PERSONAL</div>
          <h1>Your ride.<br />Your <em>journey.</em></h1>
          <p className="hero-description">
            From quick city rides to the long way home, find a vehicle that fits
            your plans — and go make the day yours.
          </p>
          <div className="hero-buttons">
            <Link className="button button-gold" to={vehicleListUrl}>
              Find your ride <ArrowRight size={17} />
            </Link>
            <a className="text-link" href="#how-it-works">How renting works</a>
          </div>
          <div className="hero-trust">
            <span className="trust-icon"><ShieldCheck size={17} /></span>
            <div><strong>Local service, thoughtful support</strong><span className="trust-caption">A real team to help you plan the details</span></div>
          </div>
        </div>

        <div className="hero-visual" role="group" aria-label="Explore cars, bikes and more">
          <div className="hero-orbit hero-orbit-one" />
          <div className="hero-orbit hero-orbit-two" />
          <div className="hero-image-frame hero-image-frame-car">
            <VehicleArtwork
              alt="A premium car ready for a road trip"
              categoryName="Car"
              className="hero-vehicle-art"
              loading="eager"
            />
            <span className="hero-image-kind">CARS</span>
          </div>
          <div className="hero-image-frame hero-image-frame-bike">
            <VehicleArtwork
              alt="A motorcycle ready for a city ride"
              categoryName="Bike"
              className="hero-vehicle-art"
              loading="eager"
            />
            <span className="hero-image-kind">BIKES</span>
          </div>
          <span className="hero-fleet-label">CARS <i /> BIKES <i /> SCOOTERS <i /> MORE</span>
          <div className="hero-image-caption">
            <span className="caption-icon"><MapPin size={15} /></span>
            <div><strong>Find your kind of ride</strong><span>{selectedCity?.name ?? 'Explore nearby'}</span></div>
          </div>
          <div className="hero-float-card">
            <span className="float-icon"><ShieldCheck size={19} /></span>
            <span><strong>Good journeys</strong><small>Start with peace of mind</small></span>
            <Check className="float-check" size={16} />
          </div>
          <span className="hero-image-index">01 <i /> 03</span>
        </div>

        <div className="hero-bottom-note">
          <span>01 / 03</span><span className="note-line" /> A better way to get there
        </div>
      </section>

      <section className="search-panel" aria-label="Plan your rental">
        <div className="search-intro">
          <span>START EXPLORING</span>
          <strong>Find your next ride</strong>
        </div>
        <div className="search-field location-field">
          <span className="search-icon"><MapPin size={18} /></span>
          <label htmlFor="search-city">PICK-UP CITY</label>
          <select id="search-city" value={cityId} onChange={(event) => setCityId(event.target.value)}>
            <option value="">All cities</option>
            {publicCities.data?.map((option) => <option key={option.id} value={option.id}>{option.name}</option>)}
          </select>
        </div>
        <div className="search-field">
          <span className="search-icon"><CalendarDays size={18} /></span>
          <label htmlFor="pickup-date">PICK-UP DATE</label>
          <input id="pickup-date" type="date" />
        </div>
        <div className="search-field">
          <span className="search-icon"><Clock3 size={18} /></span>
          <label htmlFor="rental-duration">RENTAL TYPE</label>
          <select id="rental-duration" defaultValue="Daily rental">
            <option>Hourly rental</option>
            <option>Daily rental</option>
            <option>Custom trip</option>
          </select>
        </div>
        <Link className="button button-dark search-button" to={vehicleListUrl}>
          Explore rides <ArrowRight size={17} />
        </Link>
      </section>

      <section className="intro-strip">
        <span>GOOD TO GO, WHEREVER YOU'RE GOING</span>
        <p>Simple rentals. Thoughtful service. A little more freedom in every direction.</p>
        <div className={`api-status ${apiHealth.isSuccess ? 'online' : ''}`} title={apiHealth.error instanceof Error ? apiHealth.error.message : undefined}>
          <span />
          {apiHealth.isSuccess ? 'API connected' : apiHealth.isPending ? 'Connecting to API' : 'API offline'}
        </div>
      </section>

      <section className="fleet-section section-pad" id="fleet">
        <div className="section-heading">
          <div>
            <span className="section-kicker">A RIDE FOR EVERY REASON</span>
            <h2>Where will today<br />take <em>you?</em></h2>
          </div>
          <p className="section-intro">
            Pick your kind of ride. We’ll help you with the rest — right here in
            {` ${selectedCity?.name ?? 'your city'}.`}
          </p>
        </div>
        <div className="category-grid">
          {publicCategories.data?.map(({ id, name, description }, index) => (
            <Link className="category-card" to={`/vehicles?${new URLSearchParams({ ...(cityId ? { city: cityId } : {}), category: id })}`} key={id}>
              <span className="category-visual">
                <VehicleArtwork alt="" categoryName={name} className="category-artwork" />
                <span className="category-number">{String(index + 1).padStart(2, '0')}</span>
                <span className="category-overlay" />
              </span>
              <span className="category-copy"><strong>{name}</strong><small>{description || 'Explore available vehicles'}</small></span>
              <ArrowUpRight className="category-arrow" size={18} />
            </Link>
          ))}
          {publicCategories.isSuccess && publicCategories.data.length === 0 && <p className="featured-empty">Vehicle categories will appear here.</p>}
        </div>
      </section>

      <section className="featured-section section-pad" id="featured">
        <div className="featured-heading">
          <div>
            <span className="section-kicker">A FEW GOOD OPTIONS</span>
            <h2>Made for your <em>next.</em></h2>
          </div>
          <Link className="preview-note" to={vehicleListUrl}>View all available vehicles <ArrowUpRight size={14} /></Link>
        </div>
        <div className="vehicle-grid">
          {featuredVehicles.data?.slice(0, 3).map((vehicle) => {
            const primary = vehicle.images.find((image) => image.is_primary) ?? vehicle.images[0]
            const price = vehicle.daily_rental_enabled
              ? `₹${vehicle.daily_base_price}`
              : vehicle.hourly_rental_enabled ? `₹${vehicle.hourly_base_price}` : 'Custom'
            const unit = vehicle.daily_rental_enabled ? '/ day' : vehicle.hourly_rental_enabled ? '/ hour' : ''
            return (
              <Link className="vehicle-card" to={`/vehicles/${vehicle.id}`} key={vehicle.id}>
                <div className="vehicle-image-wrap">
                  <VehicleArtwork
                    alt={`${vehicle.brand} ${vehicle.model}`}
                    categoryName={vehicle.category_name}
                    className="featured-vehicle-artwork"
                    imageUrl={primary ? apiAssetUrl(primary.image_path) : undefined}
                  />
                  <span className="vehicle-tag"><span />Available now</span>
                  <span className="vehicle-city"><MapPin size={13} /> {vehicle.city_name}</span>
                </div>
                <div className="vehicle-info">
                  <div><span className="vehicle-type">{vehicle.category_name}</span><h3>{vehicle.brand} {vehicle.model}</h3></div>
                  <div className="vehicle-price"><strong>{price}</strong><span>{unit}</span></div>
                </div>
                <div className="vehicle-footer"><span><Check size={14} /> With care, always</span><ArrowUpRight size={17} /></div>
              </Link>
            )
          })}
          {featuredVehicles.isPending && <p className="featured-empty">Loading available vehicles…</p>}
          {featuredVehicles.isError && (
            <div className="featured-empty" role="alert">
              <p>Fleet listings are temporarily unavailable{featuredVehicles.error instanceof Error ? `: ${featuredVehicles.error.message}` : '.'}</p>
              <button type="button" className="text-link" onClick={() => void featuredVehicles.refetch()}>Try again</button>
            </div>
          )}
          {featuredVehicles.isSuccess && featuredVehicles.data.length === 0 && (
            <div className="featured-empty">
              <p>{cityId ? `No available vehicles are listed in ${selectedCity?.name ?? 'this city'} right now.` : 'No vehicles are currently available to rent.'}</p>
              {cityId && <Link className="text-link" to="/vehicles">Browse every city</Link>}
            </div>
          )}
        </div>
      </section>

      <section className="rental-benefits section-pad" aria-labelledby="rental-benefits-heading">
        <div className="benefits-heading">
          <span className="section-kicker">MADE FOR REAL PLANS</span>
          <h2 id="rental-benefits-heading">The details make<br /><em>the difference.</em></h2>
        </div>
        <div className="benefit-grid">
          <article className="benefit-card">
            <span className="benefit-icon"><MapPin size={21} /></span>
            <div><h3>Choose your pickup</h3><p>Select from the available pickup locations when you make your booking.</p></div>
            <span className="benefit-index">01</span>
          </article>
          <article className="benefit-card">
            <span className="benefit-icon"><Clock3 size={21} /></span>
            <div><h3>Rent your way</h3><p>Explore hourly, daily and custom-trip options where available.</p></div>
            <span className="benefit-index">02</span>
          </article>
          <article className="benefit-card">
            <span className="benefit-icon"><ShieldCheck size={21} /></span>
            <div><h3>Local support</h3><p>Our team confirms the booking details and is here to help along the way.</p></div>
            <span className="benefit-index">03</span>
          </article>
        </div>
      </section>

      <section className="how-section section-pad" id="how-it-works">
        <div className="how-heading">
          <span className="section-kicker">FROM SEARCH TO START</span>
          <h2>A clear path to<br /><em>your next journey.</em></h2>
        </div>
        <div className="steps-grid">
          <div className="step-card"><span className="step-number">01</span><span className="step-icon"><MapPin size={22} /></span><h3>Choose your place</h3><p>Find a ride in your city and pick the option that feels right.</p></div>
          <div className="step-card"><span className="step-number">02</span><span className="step-icon"><CalendarDays size={22} /></span><h3>Tell us your plans</h3><p>Choose your dates, your ride style, and where you’ll pick up.</p></div>
          <div className="step-card"><span className="step-number">03</span><span className="step-icon"><Compass size={22} /></span><h3>Enjoy the journey</h3><p>Our team confirms the details. You take it from there.</p></div>
        </div>
      </section>

      <section className="promise-section">
        <div className="promise-icon"><ShieldCheck size={24} /></div>
        <div><span className="section-kicker">THE LNR PROMISE</span><h2>Good people. Good rides.<br /><em>No surprises.</em></h2></div>
        <p>We’re a local team that believes getting there should feel just as good as being there. Here when you need us, every step of the way.</p>
        <a className="text-link" href="#support">Get to know us <ArrowRight size={16} /></a>
      </section>

      <footer className="site-footer" id="support">
        <div className="footer-top">
          <Link className="brand footer-brand" to="/">
            <span className="brand-mark">LN</span>
            <span className="brand-name"><strong>LAXMI NARASIMHA</strong><small>RENTALS</small></span>
          </Link>
          <p>Here for the miles<br />that make the memories.</p>
          <div className="footer-links">
            {customerSession.status === 'anonymous' && <Link to="/admin/login">Admin sign in</Link>}
            <a className="footer-contact" href="#support"><PhoneCall size={17} /> Customer support</a>
          </div>
        </div>
        <div className="footer-bottom"><span>© 2026 Laxmi Narasimha Rentals</span><span>Made for the journey.</span><a href="#support">Get in touch</a></div>
      </footer>
    </main>
  )
}

function CustomerOnly({ children }: { children: ReactNode }) {
  const session = useCustomerSession()
  const location = useLocation()
  if (session.status === 'loading') {
    return <main className="auth-page"><p className="auth-loading" role="status">Checking your customer session…</p></main>
  }
  if (session.status === 'error') {
    return <main className="auth-page"><p className="auth-error" role="alert">Your session could not be verified. Please try again.</p></main>
  }
  if (session.status === 'anonymous') {
    const intendedPath = `${location.pathname}${location.search}`
    return <Navigate to={`/login?next=${encodeURIComponent(intendedPath)}`} replace />
  }
  return <Fragment key={session.customer.id}>{children}</Fragment>
}

function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/login" element={<CustomerLoginPage />} />
          <Route path="/register" element={<CustomerRegistrationPage />} />
          <Route path="/password-reset" element={<PasswordResetPage />} />
          <Route path="/password-reset/confirm" element={<PasswordResetPage confirm />} />
      <Route path="/account" element={<CustomerOnly><CustomerAccountPage /></CustomerOnly>} />
      <Route path="/admin/login" element={<AdminLoginPage />} />
      <Route path="/admin/mfa" element={<AdminMfaPage />} />
      <Route path="/admin" element={<AdminHomePage />} />
      <Route path="/admin/bookings" element={<AdminBookingsPage />} />
      <Route path="/admin/customers" element={<AdminCustomersPage />} />
      <Route path="/admin/vehicles" element={<AdminVehicleListPage />} />
      <Route path="/admin/vehicles/new" element={<VehicleFormPage />} />
      <Route path="/admin/vehicles/:vehicleId/edit" element={<VehicleFormPage />} />
      <Route path="/admin/categories" element={<AdminCatalogPage type="categories" />} />
      <Route path="/admin/cities" element={<AdminCatalogPage type="cities" />} />
      <Route path="/admin/pickup-locations" element={<AdminCatalogPage type="pickup-locations" />} />
      <Route path="/vehicles" element={<PublicVehicleListPage />} />
      <Route path="/vehicles/:vehicleId/book" element={<CustomerOnly><CustomerBookingPage /></CustomerOnly>} />
      <Route path="/vehicles/:vehicleId" element={<PublicVehicleDetailPage />} />
      <Route path="/bookings" element={<CustomerOnly><CustomerBookingHistoryPage /></CustomerOnly>} />
      <Route path="/notifications" element={<CustomerOnly><CustomerNotificationsPage /></CustomerOnly>} />
      <Route path="/unauthorized" element={<UnauthorizedPage />} />
      <Route path="/session-expired" element={<SessionExpiredPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default App
