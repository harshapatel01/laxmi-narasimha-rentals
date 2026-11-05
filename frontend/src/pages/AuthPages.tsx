import { type FormEvent, type ReactNode, useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { ArrowLeft, ArrowRight, ShieldCheck } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'

import { apiRequest, ApiError } from '../services/api'
import {
  customerPostAuthDestination,
  runAfterSuccessfulCustomerRequest,
} from '../utils/customerNavigation'
import {
  clearCustomerSession,
  refreshCustomerSession,
  useCustomerSession,
} from '../services/customerSession'

interface Customer {
  id: string
  mobile: string
  email: string | null
  mobile_verified: boolean
  status: string
  first_name: string | null
  last_name: string | null
}

interface Admin {
  id: string
  username: string
  email: string
  role: string
}

interface AdminDashboard {
  status: string
  admin: string
}

function AuthLayout({ children, eyebrow, title, description }: {
  children: ReactNode
  eyebrow: string
  title: string
  description: string
}) {
  const isAdminExperience = eyebrow.includes('ADMIN') || eyebrow.includes('TWO-FACTOR')
  const pageVariant = isAdminExperience ? 'admin' : eyebrow === 'YOUR ACCOUNT' ? 'account' : 'customer'

  return (
    <main className={`auth-page auth-page--${pageVariant}`}>
      <header className="auth-header">
        <Link className="brand" to="/" aria-label="Laxmi Narasimha Rentals home">
          <span className="brand-mark">LN</span>
          <span className="brand-name"><strong>LAXMI NARASIMHA</strong><small>RENTALS</small></span>
        </Link>
        <Link to="/" className="auth-home-link"><ArrowLeft size={16} /> Back to home</Link>
      </header>
      <section className="auth-card" aria-labelledby="auth-title">
        <div className="auth-mark"><ShieldCheck size={23} /></div>
        <p className="auth-eyebrow">{eyebrow}</p>
        <h1 id="auth-title">{title}</h1>
        <p className="auth-description">{description}</p>
        {children}
      </section>
      <footer className="auth-footer">Laxmi Narasimha Rentals · Secure account access</footer>
    </main>
  )
}

function FormError({ children }: { children: string }) {
  if (!children) return null
  return <p className="auth-error" role="alert">{children}</p>
}

function getErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message
  }
  if (error instanceof Error) return error.message
  return 'We could not reach the service. Check your connection and try again.'
}

function normalizeMobileInput(value: string): string {
  let digits = value.replace(/\D/g, '')
  if (digits.startsWith('0') && digits.length === 11) digits = digits.slice(1)
  if (digits.startsWith('91') && digits.length === 12) digits = digits.slice(2)
  if (!/^[6-9]\d{9}$/.test(digits)) {
    throw new Error('Enter a valid 10-digit Indian mobile number.')
  }
  return `+91${digits}`
}

export function CustomerLoginPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [searchParams] = useSearchParams()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setBusy(true)
    try {
      await runAfterSuccessfulCustomerRequest(
        () => apiRequest<Customer>('/auth/login', {
          method: 'POST',
          body: JSON.stringify({ email, password }),
        }),
        async () => {
          await refreshCustomerSession(queryClient)
          navigate(customerPostAuthDestination(searchParams.get('next')), { replace: true })
        },
      )
    } catch (requestError) {
      setError(getErrorMessage(requestError))
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthLayout
      eyebrow="CUSTOMER SIGN IN"
      title="Your next journey starts here."
      description="Sign in securely with the email address and password on your account."
    >
      <form className="auth-form" onSubmit={submit}>
        <label htmlFor="customer-email">Email address</label>
        <input id="customer-email" name="email" type="email" autoComplete="email" maxLength={254} value={email} onChange={(event) => setEmail(event.target.value)} required />
        <label htmlFor="customer-password">Password</label>
        <input id="customer-password" name="password" type="password" autoComplete="current-password" maxLength={256} value={password} onChange={(event) => setPassword(event.target.value)} required />
        <FormError>{error}</FormError>
        <button className="auth-submit" type="submit" disabled={busy}>
          {busy ? 'Signing in…' : 'Sign in'} <ArrowRight size={17} />
        </button>
      </form>
      <div className="auth-account-links">
        <Link to={`/password-reset${searchParams.get('next') ? `?next=${encodeURIComponent(searchParams.get('next') ?? '')}` : ''}`}>Forgot password?</Link>
        <Link to={`/register${searchParams.get('next') ? `?next=${encodeURIComponent(searchParams.get('next') ?? '')}` : ''}`}>Create an account</Link>
      </div>
    </AuthLayout>
  )
}

export function CustomerRegistrationPage() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [mobile, setMobile] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    let normalizedMobile: string
    try {
      normalizedMobile = normalizeMobileInput(mobile)
    } catch (validationError) {
      setError(getErrorMessage(validationError))
      return
    }
    if (password !== confirmPassword) {
      setError('Passwords do not match.')
      return
    }
    setBusy(true)
    try {
      await runAfterSuccessfulCustomerRequest(
        () => apiRequest<Customer>('/auth/register', {
          method: 'POST',
          body: JSON.stringify({ full_name: fullName, email, mobile: normalizedMobile, password, confirm_password: confirmPassword }),
        }),
        async () => {
          await refreshCustomerSession(queryClient)
          navigate(customerPostAuthDestination(searchParams.get('next')), {
            replace: true,
            state: { notice: 'Your account was created successfully.' },
          })
        },
      )
    } catch (requestError) {
      setError(getErrorMessage(requestError))
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthLayout
      eyebrow="CREATE CUSTOMER ACCOUNT"
      title="Start your next journey."
      description="Create an account using your email and a valid Indian mobile number."
    >
      <form className="auth-form" onSubmit={submit}>
        <label htmlFor="register-full-name">Full name</label>
        <input id="register-full-name" autoComplete="name" maxLength={160} value={fullName} onChange={(event) => setFullName(event.target.value)} required />
        <label htmlFor="register-email">Email address</label>
        <input id="register-email" type="email" autoComplete="email" maxLength={254} value={email} onChange={(event) => setEmail(event.target.value)} required />
        <label htmlFor="register-mobile">Indian mobile number</label>
        <input id="register-mobile" type="tel" inputMode="tel" autoComplete="tel-national" placeholder="+91 98765 43210" value={mobile} onChange={(event) => setMobile(event.target.value)} required />
        <span className="auth-help">Your phone is saved in normalized +91 format. It is not marked verified by registration.</span>
        <label htmlFor="register-password">Password</label>
        <input id="register-password" type="password" autoComplete="new-password" minLength={12} maxLength={256} value={password} onChange={(event) => setPassword(event.target.value)} required />
        <span className="auth-help">Use at least 12 characters.</span>
        <label htmlFor="register-confirm-password">Confirm password</label>
        <input id="register-confirm-password" type="password" autoComplete="new-password" minLength={12} maxLength={256} value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} required />
        <FormError>{error}</FormError>
        <button className="auth-submit" type="submit" disabled={busy}>
          {busy ? 'Creating account…' : 'Create account'} <ArrowRight size={17} />
        </button>
      </form>
      <p className="auth-privacy">Already registered? <Link to={`/login${searchParams.get('next') ? `?next=${encodeURIComponent(searchParams.get('next') ?? '')}` : ''}`}>Sign in</Link></p>
    </AuthLayout>
  )
}

export function PasswordResetPage({ confirm = false }: { confirm?: boolean }) {
  const [searchParams] = useSearchParams()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setMessage('')
    if (confirm && password !== confirmPassword) {
      setError('Passwords do not match.')
      return
    }
    setBusy(true)
    try {
      if (confirm) {
        await apiRequest('/auth/password-reset/confirm', {
          method: 'POST',
          body: JSON.stringify({ token: searchParams.get('token'), password, confirm_password: confirmPassword }),
        })
        setMessage('Password updated. Sign in with your new password.')
      } else {
        const result = await apiRequest<{ message: string }>('/auth/password-reset/request', {
          method: 'POST',
          body: JSON.stringify({ email }),
        })
        setMessage(result.message)
      }
    } catch (requestError) {
      setError(getErrorMessage(requestError))
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthLayout
      eyebrow="PASSWORD RECOVERY"
      title={confirm ? 'Choose a new password.' : 'Reset your password.'}
      description={confirm ? 'Use a new password to secure your customer account.' : 'If an account can be reset, instructions will be sent to its email address.'}
    >
      {confirm && !searchParams.get('token') ? <FormError>A valid reset link is required.</FormError> : (
        <form className="auth-form" onSubmit={(event) => void submit(event)}>
          {!confirm ? <>
            <label htmlFor="reset-email">Email address</label>
            <input id="reset-email" type="email" autoComplete="email" maxLength={254} value={email} onChange={(event) => setEmail(event.target.value)} required />
          </> : <>
            <label htmlFor="reset-password">New password</label>
            <input id="reset-password" type="password" autoComplete="new-password" minLength={12} maxLength={256} value={password} onChange={(event) => setPassword(event.target.value)} required />
            <label htmlFor="reset-confirm-password">Confirm new password</label>
            <input id="reset-confirm-password" type="password" autoComplete="new-password" minLength={12} maxLength={256} value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} required />
          </>}
          <FormError>{error}</FormError>
          {message && <p className="auth-success" role="status">{message}</p>}
          <button className="auth-submit" type="submit" disabled={busy || Boolean(message)}>
            {busy ? 'Please wait…' : confirm ? 'Update password' : 'Request reset link'} <ArrowRight size={17} />
          </button>
        </form>
      )}
      <Link to="/login" className="auth-back-link"><ArrowLeft size={15} /> Back to sign in</Link>
    </AuthLayout>
  )
}

export function CustomerAccountPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const session = useCustomerSession()
  const customer = session.status === 'authenticated' ? session.customer : null
  const [firstName, setFirstName] = useState(customer?.first_name ?? '')
  const [lastName, setLastName] = useState(customer?.last_name ?? '')
  const [credentialEmail, setCredentialEmail] = useState('')
  const [credentialPassword, setCredentialPassword] = useState('')
  const [credentialConfirmation, setCredentialConfirmation] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function saveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setBusy(true)
    try {
      await apiRequest<Customer>('/auth/profile', {
        method: 'PATCH',
        body: JSON.stringify({ first_name: firstName, last_name: lastName }),
      })
      await refreshCustomerSession(queryClient)
    } catch (requestError) {
      setError(getErrorMessage(requestError))
    } finally {
      setBusy(false)
    }
  }

  async function logout() {
    setError('')
    setBusy(true)
    try {
      await apiRequest('/auth/logout', { method: 'POST' })
      clearCustomerSession(queryClient)
      navigate('/', { replace: true })
    } catch (requestError) {
      if (requestError instanceof ApiError && requestError.status === 401) {
        clearCustomerSession(queryClient)
        navigate('/', { replace: true })
        return
      }
      setError(getErrorMessage(requestError))
    } finally {
      setBusy(false)
    }
  }

  async function establishCredentials(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    if (credentialPassword !== credentialConfirmation) {
      setError('Passwords do not match.')
      return
    }
    setBusy(true)
    try {
      await apiRequest<Customer>('/auth/credentials', {
        method: 'POST',
        body: JSON.stringify({
          email: credentialEmail,
          password: credentialPassword,
          confirm_password: credentialConfirmation,
        }),
      })
      await refreshCustomerSession(queryClient)
      setCredentialPassword('')
      setCredentialConfirmation('')
    } catch (requestError) {
      setError(getErrorMessage(requestError))
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthLayout eyebrow="YOUR ACCOUNT" title="Welcome back." description="Your secure customer account is ready.">
      {customer ? (
        <div className="account-details">
          <div className="account-avatar">{customer.mobile.slice(-2)}</div>
          <p><span>Email</span><strong>{customer.email ?? 'Not set'}</strong></p>
          <p><span>Mobile</span><strong>{customer.mobile}</strong></p>
          <p><span>Phone verification</span><strong>{customer.mobile_verified ? 'Verified' : 'Not verified'}</strong></p>
          <p><span>Account status</span><strong className="status-active">{customer.status}</strong></p>
          <Link className="auth-back-link" to="/bookings">View my booking history <ArrowRight size={15} /></Link>
          {!customer.email && (
            <form className="auth-form profile-form" onSubmit={(event) => void establishCredentials(event)}>
              <p className="auth-help">Set up email and password on this signed-in account to preserve its existing bookings.</p>
              <label htmlFor="credential-email">Email address</label>
              <input id="credential-email" type="email" autoComplete="email" maxLength={254} value={credentialEmail} onChange={(event) => setCredentialEmail(event.target.value)} required />
              <label htmlFor="credential-password">Password</label>
              <input id="credential-password" type="password" autoComplete="new-password" minLength={12} maxLength={256} value={credentialPassword} onChange={(event) => setCredentialPassword(event.target.value)} required />
              <label htmlFor="credential-confirm">Confirm password</label>
              <input id="credential-confirm" type="password" autoComplete="new-password" minLength={12} maxLength={256} value={credentialConfirmation} onChange={(event) => setCredentialConfirmation(event.target.value)} required />
              <button className="auth-submit" type="submit" disabled={busy}>{busy ? 'Saving credentials…' : 'Set up email sign-in'} <ArrowRight size={17} /></button>
            </form>
          )}
          <form className="auth-form profile-form" onSubmit={saveProfile}>
            <label htmlFor="profile-first-name">First name</label>
            <input id="profile-first-name" autoComplete="given-name" maxLength={80} value={firstName} onChange={(event) => setFirstName(event.target.value)} />
            <label htmlFor="profile-last-name">Last name</label>
            <input id="profile-last-name" autoComplete="family-name" maxLength={80} value={lastName} onChange={(event) => setLastName(event.target.value)} />
            <button className="auth-submit" type="submit" disabled={busy}>
              {busy ? 'Saving…' : 'Save profile'} <ArrowRight size={17} />
            </button>
          </form>
          <FormError>{error}</FormError>
          <button className="auth-submit" type="button" onClick={logout} disabled={busy}>
            {busy ? 'Signing out…' : 'Sign out'} <ArrowRight size={17} />
          </button>
        </div>
      ) : <p className="auth-loading">Checking your session…</p>}
    </AuthLayout>
  )
}

export function AdminLoginPage() {
  const navigate = useNavigate()
  const [identity, setIdentity] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const result = await apiRequest<{ mfa_required: boolean }>('/admin/auth/login', {
        method: 'POST',
        body: JSON.stringify({ username_or_email: identity, password }),
      })
      navigate(result.mfa_required ? '/admin/mfa' : '/admin', { replace: true })
    } catch (requestError) {
      setError(getErrorMessage(requestError))
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthLayout eyebrow="ADMIN ACCESS" title="Sign in to your workspace." description="Use your administrator account and password to continue.">
      <form className="auth-form" onSubmit={submit}>
        <label htmlFor="admin-identity">Email or username</label>
        <input id="admin-identity" autoComplete="username" value={identity} onChange={(event) => setIdentity(event.target.value)} required />
        <label htmlFor="admin-password">Password</label>
        <input id="admin-password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required />
        <FormError>{error}</FormError>
        <button className="auth-submit" type="submit" disabled={busy}>
          {busy ? 'Checking credentials…' : 'Continue'} <ArrowRight size={17} />
        </button>
      </form>
      <p className="auth-privacy">Sign-in requirements are enforced by the server’s security policy.</p>
    </AuthLayout>
  )
}

export function AdminMfaPage() {
  const navigate = useNavigate()
  const [code, setCode] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function verify(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      await apiRequest<Admin>('/admin/auth/mfa/verify', {
        method: 'POST',
        body: JSON.stringify({ code }),
      })
      navigate('/admin', { replace: true })
    } catch (requestError) {
      setError(getErrorMessage(requestError))
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthLayout eyebrow="TWO-FACTOR VERIFICATION" title="Confirm it’s you." description="Enter the current six-digit code from your authenticator app.">
      <form className="auth-form" onSubmit={verify}>
        <label htmlFor="admin-mfa-code">Authenticator code</label>
        <input className="code-input" id="admin-mfa-code" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} value={code} onChange={(event) => setCode(event.target.value.replace(/\D/g, '').slice(0, 6))} required />
        <FormError>{error}</FormError>
        <button className="auth-submit" type="submit" disabled={busy || code.length !== 6}>
          {busy ? 'Verifying…' : 'Verify and continue'} <ArrowRight size={17} />
        </button>
      </form>
      <Link to="/admin/login" className="auth-back-link"><ArrowLeft size={15} /> Return to admin sign in</Link>
    </AuthLayout>
  )
}

export function AdminDashboardPage() {
  const navigate = useNavigate()
  const [admin, setAdmin] = useState<Admin | null>(null)
  const [dashboard, setDashboard] = useState<AdminDashboard | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    Promise.all([
      apiRequest<Admin>('/admin/auth/me'),
      apiRequest<AdminDashboard>('/admin/dashboard'),
    ])
      .then(([currentAdmin, data]) => {
        setAdmin(currentAdmin)
        setDashboard(data)
      })
      .catch((requestError: unknown) => {
        navigate(requestError instanceof ApiError && requestError.status === 401 ? '/session-expired' : '/unauthorized', { replace: true })
      })
  }, [navigate])

  async function logout() {
    setError('')
    try {
      await apiRequest('/admin/auth/logout', { method: 'POST' })
      navigate('/admin/login', { replace: true })
    } catch (requestError) {
      setError(getErrorMessage(requestError))
    }
  }

  return (
    <AuthLayout eyebrow="ADMIN DASHBOARD" title="Operations overview." description="Protected administrator workspace.">
      {admin && dashboard ? (
        <div className="account-details">
          <div className="dashboard-welcome"><ShieldCheck size={20} /><span>Signed in as <strong>{admin.username}</strong></span></div>
          <p><span>Administrator role</span><strong>{admin.role}</strong></p>
          <p><span>Workspace status</span><strong className="status-active">{dashboard.status}</strong></p>
          <FormError>{error}</FormError>
          <button className="auth-submit" type="button" onClick={logout}>Sign out <ArrowRight size={17} /></button>
        </div>
      ) : <p className="auth-loading">Verifying administrator session…</p>}
    </AuthLayout>
  )
}

export function UnauthorizedPage() {
  return (
    <AuthLayout eyebrow="ACCESS RESTRICTED" title="You can’t access this page." description="Your account does not have permission to view this area.">
      <Link className="auth-submit auth-link-button" to="/"><span>Return home</span><ArrowRight size={17} /></Link>
    </AuthLayout>
  )
}

export function SessionExpiredPage() {
  return (
    <AuthLayout eyebrow="SESSION ENDED" title="Please sign in again." description="For your security, this session is no longer active.">
      <div className="session-actions">
        <Link className="auth-submit auth-link-button" to="/login"><span>Customer sign in</span><ArrowRight size={17} /></Link>
        <Link className="auth-secondary-link" to="/admin/login">Administrator sign in</Link>
      </div>
    </AuthLayout>
  )
}
