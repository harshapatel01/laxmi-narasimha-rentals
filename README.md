# Laxmi Narasimha Rentals

Phase 1 project foundation, Phase 2 authentication, and Phase 3 vehicle management for a vehicle-rental platform. The frontend uses React, TypeScript, Vite, Tailwind CSS, React Router, and TanStack Query. The backend uses FastAPI, Pydantic Settings, SQLAlchemy 2, psycopg 3, and Alembic. PostgreSQL remains the existing database; setup and migrations do not recreate or reset it.

## Requirements

- Windows 10/11
- Python 3.12 or newer
- Node.js 20.19 or newer and npm
- The existing PostgreSQL service and `laxmi_narasimha_rentals` database

## Configure the backend

From the workspace root, copy the example configuration:

```powershell
Copy-Item backend\.env.example backend\.env
```

Edit `backend\.env` locally and set `DB_PASSWORD` to the password already assigned to `lnr_app`. Do not paste the password into chat or commit the `.env` file. The connection URL is assembled safely from separate settings, including passwords containing reserved URL characters.

Generate and persist the missing authentication keys locally (the command does not print their values):

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -c "from pathlib import Path; import secrets; from cryptography.fernet import Fernet; p=Path('.env'); s=p.read_text(); additions=[]; additions += [] if 'AUTH_SECRET_KEY=' in s else ['AUTH_SECRET_KEY='+secrets.token_urlsafe(48)]; additions += [] if 'TOTP_ENCRYPTION_KEY=' in s else ['TOTP_ENCRYPTION_KEY='+Fernet.generate_key().decode()]; p.write_text(s.rstrip() + ('\n' + '\n'.join(additions) + '\n' if additions else ''), encoding='utf-8')"
Set-Location ..
```

`AUTH_SECRET_KEY` signs/digests opaque session and password-reset material. `TOTP_ENCRYPTION_KEY` encrypts admin authenticator secrets at rest. Back up these keys securely; changing either invalidates customer sessions or prevents admin MFA secrets from decrypting. Keep both only in `backend\.env` for local work and use a managed secret store in production.

Create the virtual environment and install the backend dependencies (already done in this workspace):

```powershell
python -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

Start the API from the `backend` directory:

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

The API is available at `http://localhost:8000`; interactive OpenAPI docs are at `http://localhost:8000/docs`. `GET /health` checks the API process. `GET /api/v1/health/database` checks PostgreSQL with `SELECT 1` and reports connection failures without exposing credentials.

Phase 2's initial migration creates only `users`, `customer_profiles`, `admin_accounts`, `otp_verification_records`, `authentication_sessions`, and `authentication_audit_logs`. Phase 3 adds `cities`, `pickup_locations`, `vehicle_categories`, `vehicles`, and `vehicle_images` using an additive migration. Do not use `Base.metadata.create_all()` to manage the development schema. Future migration commands must be run from `backend`:

```powershell
Set-Location backend
.\.venv\Scripts\alembic.exe upgrade head
```

The existing database is never recreated or reset by these setup steps.

## Customer email/password authentication

Customers register at `http://localhost:5173/register` with a name, unique email, valid Indian mobile number, and matching password fields. Registration starts a secure customer session. Sign in at `http://localhost:5173/login`; booking pages return the customer to the requested vehicle or booking history after sign-in. Passwords are hashed with Argon2id. Customer session cookies remain HttpOnly/SameSite=Strict with CSRF checks on writes; failed logins trigger lockout and IP rate limits. Registration does not verify a phone; account responses explicitly report `mobile_verified=false`, and booking requests require a valid saved Indian mobile number.

After successful registration or login, customers return to a validated internal destination when one was requested (for example a booking page); otherwise they go to `/`. Login and registration refresh shared customer state from the backend `/auth/me` endpoint before navigating. The shared customer navigation on `/`, `/vehicles`, vehicle details, and booking pages is restored from `/auth/me` after refresh. Customer-only pages wait for session verification and redirect anonymous users to sign in. The backend still enforces customer sessions and CSRF independently of frontend route guards. Session cookies are HttpOnly, SameSite Strict, Secure outside local development/test, and revoked on logout; private API responses are marked no-store. Logout is synchronized across same-browser tabs, which normally share the same cookie-backed session; separate browser profiles do not share cookies.

Customer authentication is cookie-backed, not stored in `localStorage` or `sessionStorage` and not carried in URLs. A copied protected URL alone does not grant access: a different device, browser profile, or private/incognito window must have its own valid server session cookie. Browser tabs in one profile intentionally share that cookie and logout revokes the shared server-side session. **Requiring fresh login in every newly opened tab is not implemented:** browsers do not provide a trustworthy, universal tab identity to the server; same-origin cookies are shared, and duplicated tabs may clone `sessionStorage`. A frontend-only tab token would therefore not be a reliable security boundary. If per-tab reauthentication is a business requirement, use an explicit fresh-credential/step-up challenge for protected actions or a separately isolated browser profile; do not treat a URL or client-supplied tab ID as proof of identity.

Existing OTP-only accounts retain their user IDs and booking links. An owner with a still-valid customer session can set email/password from `/account`, which attaches credentials to that same account. Do not register a new account using another customer’s phone number to claim their history. Accounts without a valid session require a support-led identity process.

Password reset tokens are random, time-limited, stored only as keyed hashes, single-use, and revoke prior customer sessions. Reset and booking notification emails use the Brevo Transactional Email API. Configure `BREVO_API_KEY`, `BREVO_SENDER_EMAIL` (a verified sender), and `BREVO_SENDER_NAME` in the backend environment; keep the API key only in backend configuration and never add a `VITE_` prefix. The reset endpoint always returns the same generic accepted response for known/unknown emails, including unavailable or failed delivery; provider failures are recorded without exposing account details to the caller.

Password reset requests are rate-limited to 10 attempts per IP per 15 minutes and 3 attempts per keyed email identifier per hour by default. These limits can be adjusted with `PASSWORD_RESET_IP_LIMIT`, `PASSWORD_RESET_IP_WINDOW_MINUTES`, `PASSWORD_RESET_EMAIL_LIMIT`, and `PASSWORD_RESET_EMAIL_WINDOW_MINUTES`. Each attempt is committed before account lookup or email delivery so provider failures still count. PostgreSQL advisory locks serialize concurrent requests for the same IP/email rate-limit keys. Rate-limit audit records contain keyed email hashes, not raw email addresses. Incomplete Brevo API configuration prevents delivery but does not produce an account-dependent response.

The old OTP API routes and frontend verification page have been removed. The standalone OTP table and its two current rows remain intact pending explicit approval for any destructive migration.

## Booking workflow, notifications, and manual WhatsApp

Customers submit unpaid booking requests at `/vehicles/{vehicle-id}/book`; they can choose an active pickup location in the vehicle's city (available options come from `GET /api/v1/pickup-locations?city={city-id}`). A new request remains **Pending** until an administrator confirms or rejects it. Pending requests do not reserve a vehicle. Confirmation rechecks vehicle and selected-location eligibility and overlapping confirmed bookings while holding a PostgreSQL vehicle row lock. Customer booking history and payment balance are available at `/bookings`. Admins can search by booking reference, customer name/email/mobile, and vehicle, manage requests at `/admin/bookings`, record Cash/UPI/Bank Transfer advances with separate reference and notes, and set custom-trip quotations. Online checkout remains unavailable; no Razorpay checkout, orders, keys, or webhooks are enabled.

### Current fleet dashboard and booking availability

The existing admin dashboard keeps its fleet, role, quick-action, and setup widgets; a live fleet section is appended below them. `GET /api/v1/admin/dashboard/vehicle-stats` is admin-authenticated and returns:

- **Currently on rent:** distinct vehicles with a `confirmed` booking whose interval includes the current instant (`start_at <= now < end_at`). Pending, awaiting-payment, rejected, cancelled, completed, expired, future, and past bookings do not count. The customer and booking details are included for admin operations. Times are displayed in `Asia/Kolkata`.
- **Upcoming confirmed bookings:** confirmed bookings with `start_at > now` and `end_at > now`, shown separately with their vehicle and booking details. A vehicle with a future booking is not currently on rent; it may still be available now, but that does not imply availability during the future booking period.
- **Available now:** active vehicles marked `available`, with active city, category, and same-city pickup location, at least one usable rental mode (a configured hourly/daily price or custom trips), and no confirmed booking active now. Maintenance/inactive vehicles and vehicles currently on rent are excluded. Pending and awaiting-payment requests do not reserve time. This count is for **now**, not a promise of availability for a later period.
- The current-rental and upcoming-booking lists are classified from the same confirmed-booking query and one timezone-aware UTC instant (rendered in `Asia/Kolkata`). The set of vehicles classified as currently on rent is also the exclusion set for Available Now, so counts are derived from their corresponding response lists and those lists cannot disagree or overlap.
- Counts are calculated from a consistent database snapshot; the dashboard refreshes on focus and every 15 seconds while visible, and provides a manual refresh. If the business later wants a pending-request hold, configure an explicit short hold duration with expiry/release and transactional enforcement rather than silently treating all pending requests as reservations.

Booking pickup/return inputs use India Standard Time (`Asia/Kolkata`) regardless of the customer's device timezone and are sent to the API as timezone-aware UTC instants. Availability uses half-open intervals `[pickup, return)`: overlapping means `existing.start_at < requested.end_at` and `existing.end_at > requested.start_at`, so a pickup exactly at another return time is allowed. Only confirmed bookings reserve periods; all supported rental modes use the same interval check. The form debounces availability checks, disables submission while checking or on errors/unavailability, and the API checks again on request creation. A retried identical customer request while its earlier request is pending returns the existing booking rather than creating duplicate booking/notification/email-job records.

Every booking confirmation path locks the vehicle row in PostgreSQL and checks for a confirmed overlap in the same transaction. This serializes competing confirmations for the same vehicle; a losing request receives HTTP 409 and must select another period. Customer-created pending requests also lock and recheck the vehicle, but remain non-reserving until confirmed. The existing PostgreSQL database schema already contains the required booking fields and indexes, so this change does not require a migration. Direct database writes that bypass the application transaction are outside this protection.

Booking request, confirmation, rejection/cancellation, and relevant payment events create a customer-owned PostgreSQL notification in the same transaction as the booking event. Customers can review them at `/notifications`; the unread count is shown in the customer navigation. The API provides `GET /api/v1/notifications`, `GET /api/v1/notifications/unread-count`, and CSRF-protected `POST /api/v1/notifications/{notification-id}/read`. Notifications remain after logout, are private to the owning customer, and link back to the relevant booking.

### Configure Brevo (optional)

1. Create a Brevo account and use its available transactional-email offering; this integration does not require a paid-only feature.
2. In Brevo, add and verify the sender email (or verify the sending domain and use an address on that domain) under the sender/domain settings. Complete any domain authentication steps Brevo presents before production use.
3. Generate an API key from the Brevo API keys page. Store it only in `backend\.env` as `BREVO_API_KEY`; also set `BREVO_SENDER_EMAIL` to the verified sender and `BREVO_SENDER_NAME` to the desired display name. Set `BOOKING_ADMIN_EMAIL` to the business inbox that should receive new customer booking requests; it is independent of the verified sender address.
4. Restart FastAPI and create a test booking using a customer account with an email address. Inspect admin-only delivery diagnostics at `GET /api/v1/admin/bookings/notifications/email-jobs` and customer website notices at `GET /api/v1/notifications`.

The backend sends through Brevo's transactional email API. No API key is sent to the frontend. Customer and admin recipients are stored as independent, event-keyed email jobs. A new customer booking request queues an acknowledgment for the customer's account email and a separate message for `BOOKING_ADMIN_EMAIL`; later booking/payment updates go to the customer. Missing sender/recipient configuration is recorded as `not_configured`, definite provider rejections as `failed`, a 2xx response as `accepted_by_provider`, and timeouts or provider 5xx responses as `delivery_unknown`. Provider acceptance does not prove inbox delivery. A booking commit is not rolled back when email delivery fails.

Only active `owner`, `admin`, and `manager` accounts can view diagnostics or retry jobs. Inspect `sending` and `delivery_unknown` jobs before any manual retry because a provider may already have accepted the message. Eligible jobs can be retried explicitly through `POST /api/v1/admin/bookings/notifications/email-jobs/{job-id}/retry`; the API does not expose recipient email addresses in diagnostic responses. The legacy customer-only diagnostics remain at `GET /api/v1/admin/bookings/notifications/email`.

Admin booking cards include an **Open WhatsApp message** link for Pending, Confirmed, Rejected, and Cancelled bookings. It validates the saved Indian mobile number and opens WhatsApp with a URL-encoded draft containing the booking reference, customer, vehicle, dates, and status. An administrator must review and manually send the message in WhatsApp; opening the link does not deliver it.

### WhatsApp Cloud API webhook (incoming callbacks only)

Configure `WHATSAPP_WEBHOOK_VERIFY_TOKEN` with a strong random verification token and `WHATSAPP_APP_SECRET` with the Meta App Secret in the backend environment, then restart FastAPI. Register `https://<your-api-host>/api/v1/webhooks/whatsapp` as the Meta callback URL and provide the same verification token in Meta's webhook setup. The GET endpoint verifies Meta's subscription challenge; POST callbacks are accepted only with a valid `X-Hub-Signature-256` HMAC-SHA256 signature. Delivery status callbacks are parsed and safely logged as status counts only; they are not persisted or correlated to bookings. This webhook does not send WhatsApp messages and does not change the existing manual WhatsApp draft workflow.

### WhatsApp Cloud API outbound booking notifications

Outbound messages are disabled until configured. Set these backend-only environment variables and restart FastAPI:

- `WHATSAPP_ACCESS_TOKEN`: Meta access token with WhatsApp messaging permissions.
- `WHATSAPP_PHONE_NUMBER_ID`: sender phone-number ID from the WhatsApp Business Platform.
- `WHATSAPP_ADMIN_PHONE_NUMBER`: admin recipient in international format, such as `+91...`.
- `WHATSAPP_API_VERSION`: supported Graph API version, in `vNN.N` format.
- `WHATSAPP_BOOKING_TEMPLATE_NAME`: leave unset until the custom booking template is approved.
- `WHATSAPP_BOOKING_TEMPLATE_LANGUAGE`: approved template language code; defaults to `en_US`.

The explicit test command sends Meta's generic `hello_world` template to `WHATSAPP_ADMIN_PHONE_NUMBER`; it contains no booking details and is never used for booking notifications. For a Meta test sender, use its phone-number ID and access token, add the recipient number as an allowed test recipient in Meta's WhatsApp setup, then run from `backend`:

```powershell
.\.venv\Scripts\python.exe -m app.cli test-whatsapp
```

Only a newly created customer booking triggers an outbound notification, after the booking transaction commits. Identical request retries return the existing booking and do not send again. Provider/network failures are logged without message bodies or credentials and do not undo or fail the booking request. No customer decision message is sent automatically; the admin's existing manual WhatsApp decision button is unchanged.

To enable booking details, create and submit an approved WhatsApp **Utility** template in Meta Business Manager using the exact body and placeholder order below, then set `WHATSAPP_BOOKING_TEMPLATE_NAME` to its approved template name and `WHATSAPP_BOOKING_TEMPLATE_LANGUAGE` to its approved language:

```text
New booking request {{1}}
Customer: {{2}}
Vehicle: {{3}}
Category: {{4}}
Pickup location: {{5}}
Pickup: {{6}}
Return: {{7}}
Status: {{8}}
```

The placeholders map to booking reference, customer name, vehicle name, vehicle category, pickup location, pickup date/time, return date/time, and current booking status. Do not configure this template name before Meta approves a template with the matching body parameters. Production use requires a production-capable access token, the production sender phone-number ID, and an API version supported by Meta; the hello_world template is only a connectivity test.

The additive migration `e4b9c31a7d20` creates `booking_notifications` and adds optional payment notes to `booking_payments`. Revision `f1a2b3c4d5e6` creates the independent booking email-job outbox. Both migrations preserve existing booking, customer, vehicle, and payment records.

## Admin bootstrap and MFA

After applying migrations, create the first administrator from `backend`:

```powershell
.\.venv\Scripts\python.exe -m app.cli bootstrap-admin
```

The command prompts for a username, email, and 12+ character password without echoing the password, creates an `owner` account only if no admin exists, and prints a one-time TOTP provisioning URI. Add that URI to an authenticator app immediately; treat it as a secret. The admin login requires password and a six-digit TOTP code. Passwords use Argon2id, MFA secrets are Fernet-encrypted at rest, failed passwords trigger account lockout and IP rate limits, and authentication events are audited. Customer registration cannot create admins.

Admin MFA is required by default (`ADMIN_MFA_REQUIRED=true`). For local development only, password-only admin login can be enabled by setting both `APP_ENV=development` and `ADMIN_MFA_REQUIRED=false` in `backend\.env`, then restarting the backend. The backend only honors this override for requests whose direct client address is a loopback address; remote clients still require MFA. Production and every non-development environment always require MFA even if the setting is false. The backend chooses the policy and returns whether MFA is required; the frontend does not send an MFA policy flag.

To re-enable MFA, set `ADMIN_MFA_REQUIRED=true` in `backend\.env` (or remove that setting, since true is the default) and restart the backend. Then use the existing authenticator. Accounts with pending MFA setup can sign in only while the local development override is active; set up or reset MFA before requiring it again.

To securely replace MFA for an existing administrator, run this from a local interactive PowerShell terminal in `backend`:

```powershell
.\.venv\Scripts\python.exe -m app.cli reset-admin-mfa
```

The CLI asks for the admin username/email and current password (hidden input), rotates the encrypted secret, revokes active admin sessions, and prints the new provisioning URI only to that terminal. Enter a code from the newly configured authenticator to complete setup. Admin login remains blocked until that code is verified; if verification fails repeatedly or the command is interrupted, rerun the reset command. The command refuses non-interactive terminals and is not exposed as an API endpoint.

## Phase 2 API

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/v1/auth/register` | Register customer with email, password and required mobile |
| `POST` | `/api/v1/auth/login` | Customer email/password sign-in |
| `POST` | `/api/v1/auth/credentials` | Set up credentials on a signed-in legacy customer account |
| `POST` | `/api/v1/auth/password-reset/request` | Request an email-delivered reset link |
| `POST` | `/api/v1/auth/password-reset/confirm` | Consume a one-time password reset link |
| `POST` | `/api/v1/auth/logout` | CSRF-protected customer logout |
| `GET` | `/api/v1/auth/me` | Current customer/profile |
| `PATCH` | `/api/v1/auth/profile` | CSRF-protected profile update |
| `POST` | `/api/v1/admin/auth/login` | Admin password step |
| `POST` | `/api/v1/admin/auth/mfa/verify` | Admin TOTP step |
| `POST` | `/api/v1/admin/auth/logout` | CSRF-protected admin logout |
| `GET` | `/api/v1/admin/auth/me` | Current authorized admin |
| `GET` | `/api/v1/admin/dashboard` | Example role-protected admin page data |

## Phase 3 vehicle management

The admin vehicle workspace is available at `http://localhost:5173/admin`. Sign in with the existing administrator account. Before adding a vehicle, create an active city, vehicle category, and pickup location from the admin navigation. Then open `http://localhost:5173/admin/vehicles/new`, complete the vehicle details, select a pickup location belonging to the selected city, choose at least one service mode and rental mode, enter prices for enabled hourly/daily rentals, and save. Optionally select photos before saving; the first uploaded image becomes the primary photo. Existing images can be reordered by choosing a primary photo or removed from the edit page.

Customer management is at `http://localhost:5173/admin/customers`. Admins can search by name, email or mobile, inspect booking history, and block/unblock customers. Every status change requires a fresh confirmation of the authenticated administrator's password; blocking revokes the customer's sessions. Inactive vehicles remain visible at `/admin/vehicles`; Activate makes an inactive vehicle available, while an active vehicle in maintenance stays in maintenance when activated.

The customer catalog is at `http://localhost:5173/vehicles`; vehicle details use `/vehicles/{vehicle-id}`. Catalog filters are sent to the backend, including selected city and category IDs, and the API returns only active vehicles with available status and active city/category/pickup location records. Maintenance and inactive vehicles are not publicly listed. Homepage featured vehicles come from this same public API and city filter.

Admin catalog and vehicle APIs are under `/api/v1/admin/` and require the existing admin session; write operations also require CSRF validation. Public catalog endpoints are `GET /api/v1/cities`, `GET /api/v1/categories`, `GET /api/v1/vehicles`, and `GET /api/v1/vehicles/{vehicle_id}`. Vehicle prices use decimal/numeric values. Uploaded photos accept verified JPEG, PNG, or WebP content, are limited to 8 MiB each and 10 images per upload, and are re-encoded with generated filenames. Local files are stored under `backend\uploads\vehicles` when the backend runs from its directory and served under `/uploads/vehicles`. Set `VEHICLE_IMAGE_STORAGE_PATH` to an appropriate persistent storage directory when deploying.

After applying a migration, verify the revision and schema from `backend`:

```powershell
.\.venv\Scripts\alembic.exe current
.\.venv\Scripts\alembic.exe check
```

Auth cookies are `HttpOnly` and `SameSite=Strict`. They are `Secure` by default in production, staging, and other non-development/test environments; that protection cannot be disabled there. Local development/test defaults to HTTP-compatible cookies. Set `SECURE_COOKIES=true` when local development is served over HTTPS.

## Configure and run the frontend

The default API URL is `http://localhost:8000`. To override it, copy the example and edit the URL:

```powershell
Copy-Item frontend\.env.example frontend\.env
```

Install dependencies (already done in this workspace) and start Vite:

```powershell
Set-Location frontend
npm.cmd install
npm.cmd run dev
```

Open the local URL printed by Vite (normally `http://localhost:5173`). The homepage is responsive and includes a city selector, rental search controls, category browsing, and a visible API connection status. Featured vehicle cards and the public catalog are fetched from the API; no vehicle inventory is hardcoded in the frontend.

## Validation

From `frontend`:

```powershell
npm.cmd run build
```

From `backend`:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) '.venv\Lib\site-packages')
.\.venv\Scripts\python.exe -m pytest
$testExitCode = $LASTEXITCODE
Remove-Item Env:PYTHONPATH
if ($testExitCode -ne 0) { exit $testExitCode }
```

The path override works around the `py.py` module bundled with some Windows Python 3.14 installations shadowing pytest's compatibility package. If the project virtual environment is not present, create it from `backend\requirements.txt` before running tests.

Backend tests use an in-memory SQLite database through dependency overrides; they do not connect to, truncate, or reset the development PostgreSQL database. The test suite covers customer email/password registration/login, duplicate identity rejection, reset token lifecycle, session/CSRF security, admin customer search and status management, password confirmation throttling, session revocation, admin password/MFA, role denial, customer/admin separation, vehicle authorization and validation, city/category/pickup-location deactivation/reactivation, city/location consistency, public filters, inactive-vehicle visibility, image upload validation, booking lifecycle, availability checks, manual confirmation, offline payment references and notes, quotations, email delivery state/idempotency, customer notification ownership/read status, WhatsApp link formatting, and audit history.

To run the optional PostgreSQL row-lock concurrency test, provide a dedicated PostgreSQL database whose name ends in `_test` using `BOOKING_TEST_DATABASE_URL`. The test creates a unique temporary schema inside that test database and drops only that schema afterward; it refuses non-PostgreSQL databases or databases without the `_test` suffix. It is skipped when the variable is absent. Never point it at the development or production database.

## Phase boundaries and production setup

Phase 1 provides the app skeleton, environment-based PostgreSQL configuration, database health check, Alembic setup, frontend health communication, and homepage. Phase 2 adds customer email/password authentication, separate admin password/TOTP authentication, secure sessions, a protected dashboard shell, and account pages. Phase 3 adds vehicle/city/category/pickup-location management, validated image uploads, protected admin pages, and public vehicle browsing. Phase 4 adds customer booking requests and history, admin booking management and manual confirmation, custom-trip quotations, payment records, and auditable status changes. Booking requests remain pending until an admin confirms them; they do not reserve inventory.

Razorpay integration and payment-provider webhook/signature verification are not implemented. Online payment is labeled "Coming soon"; no frontend payment success can confirm a booking. SMS is no longer used for customer sign-in. Configure and verify Brevo transactional email delivery before enabling password reset in production. Production deployment requires HTTPS, strong per-environment secrets, restrictive origin/CORS settings, monitoring and alerting for auth/booking audit events, persistent image storage, and operational review of rate limits/retention.
