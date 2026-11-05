import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.api.v1.dependencies import (
    ADMIN_SESSION_COOKIE,
    ADMIN_CSRF_COOKIE,
    get_admin_challenge_with_csrf,
    get_admin_session,
    get_admin_session_with_csrf,
)
from app.core.config import get_settings
from app.db.session import get_db
from app.models.auth import AdminAccount, AuthAuditLog, AuthSession, CustomerProfile, User
from app.models.bookings import Booking
from app.models.vehicles import City, PickupLocation, Vehicle, VehicleCategory
from app.schemas.auth import (
    AdminLoginRequest,
    AdminLoginResponse,
    AdminResponse,
    MessageResponse,
    MfaVerificationRequest,
)
from app.schemas.dashboard import (
    AdminVehicleDashboardResponse,
    AvailableVehicleItem,
    CurrentRentalItem,
    UpcomingBookingItem,
)
from app.services.security import (
    decrypt_totp_secret,
    hash_token,
    new_session_tokens,
    password_hasher,
    verify_totp,
)

logger = logging.getLogger(__name__)
auth_router = APIRouter(prefix="/admin/auth", tags=["admin authentication"])
admin_router = APIRouter(prefix="/admin", tags=["admin"])
_dummy_password_hash = password_hasher.hash(secrets.token_urlsafe(32))
MAX_ADMIN_PASSWORD_FAILURES = 5
MAX_MFA_FAILURES = 5


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _set_admin_cookies(response: Response, token: str, csrf_token: str, max_age: int) -> None:
    settings = get_settings()
    response.set_cookie(
        ADMIN_SESSION_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        secure=settings.cookies_are_secure,
        samesite="none",
        path="/",
    )
    response.set_cookie(
        ADMIN_CSRF_COOKIE,
        csrf_token,
        max_age=max_age,
        httponly=False,
        secure=settings.cookies_are_secure,
        samesite="none",
        path="/",
    )


@auth_router.post("/login", response_model=AdminLoginResponse)
def admin_login(
    payload: AdminLoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> AdminLoginResponse:
    now = datetime.now(UTC)
    account = db.scalar(
        select(AdminAccount).where(
            or_(
                func.lower(AdminAccount.username) == payload.username_or_email.lower(),
                func.lower(AdminAccount.email) == payload.username_or_email.lower(),
            )
        )
    )
    password_hash = account.password_hash if account else _dummy_password_hash
    try:
        password_valid = password_hasher.verify(password_hash, payload.password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        password_valid = False

    ip_failures = db.scalar(
        select(func.count()).select_from(AuthAuditLog).where(
            AuthAuditLog.action == "admin_login_failed",
            AuthAuditLog.request_ip == _client_ip(request),
            AuthAuditLog.created_at >= now - timedelta(minutes=15),
        )
    ) or 0
    lock_expiry = account.locked_until if account else None
    if lock_expiry is not None and lock_expiry.tzinfo is None:
        lock_expiry = lock_expiry.replace(tzinfo=UTC)
    locked = (
        account is not None
        and (account.status != "active" or (lock_expiry is not None and lock_expiry > now))
    )
    if not password_valid or account is None or locked or ip_failures >= 20:
        if account is not None:
            account.failed_login_attempts += 1
            if account.failed_login_attempts >= MAX_ADMIN_PASSWORD_FAILURES:
                account.locked_until = now + timedelta(minutes=15)
        db.add(
            AuthAuditLog(
                admin_id=account.id if account else None,
                action="admin_login_failed",
                request_ip=_client_ip(request),
            )
        )
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid credentials or account temporarily unavailable.")

    settings = get_settings()
    request_host = request.client.host if request.client else None
    mfa_required = settings.requires_admin_mfa(request_host)
    if mfa_required and not account.mfa_configured:
        db.add(
            AuthAuditLog(
                admin_id=account.id,
                action="admin_mfa_setup_required",
                request_ip=_client_ip(request),
            )
        )
        db.commit()
        raise HTTPException(
            status_code=403,
            detail="Administrator MFA setup must be completed from the local CLI.",
        )

    account.failed_login_attempts = 0
    account.locked_until = None
    session_token, csrf_token = new_session_tokens()
    session_hours = settings.admin_session_hours
    session_lifetime = (
        timedelta(minutes=5)
        if mfa_required
        else timedelta(hours=session_hours)
    )
    challenge = AuthSession(
        admin_id=account.id,
        token_hash=hash_token(session_token),
        csrf_token_hash=hashlib.sha256(csrf_token.encode("utf-8")).hexdigest(),
        is_mfa_verified=not mfa_required,
        expires_at=now + session_lifetime,
    )
    db.add(challenge)
    db.add(
        AuthAuditLog(
            admin_id=account.id,
            action="admin_login" if not mfa_required else "admin_password_verified",
            request_ip=_client_ip(request),
        )
    )
    db.commit()
    _set_admin_cookies(
        response,
        session_token,
        csrf_token,
        int(session_lifetime.total_seconds()),
    )
    return AdminLoginResponse(mfa_required=mfa_required)


@auth_router.post("/mfa/verify", response_model=AdminResponse)
def verify_admin_mfa(
    payload: MfaVerificationRequest,
    request: Request,
    response: Response,
    challenge: AuthSession = Depends(get_admin_challenge_with_csrf),
    db: Session = Depends(get_db),
) -> AdminResponse:
    admin = db.get(AdminAccount, challenge.admin_id)
    if admin is None or admin.status != "active" or not admin.mfa_configured:
        raise HTTPException(status_code=401, detail="Authentication required.")
    recent_mfa_failures = db.scalar(
        select(func.count()).select_from(AuthAuditLog).where(
            AuthAuditLog.action == "admin_mfa_failed",
            AuthAuditLog.request_ip == _client_ip(request),
            AuthAuditLog.created_at >= datetime.now(UTC) - timedelta(minutes=15),
        )
    ) or 0
    if recent_mfa_failures >= 20:
        raise HTTPException(status_code=429, detail="Too many verification attempts. Try again later.")
    try:
        secret = decrypt_totp_secret(admin.totp_secret_encrypted)
    except (InvalidToken, ValueError, UnicodeDecodeError) as exc:
        logger.exception("Unable to decrypt administrator MFA configuration")
        raise HTTPException(status_code=503, detail="Administrator MFA is unavailable.") from exc
    if not verify_totp(secret, payload.code):
        challenge.mfa_attempts += 1
        db.add(
            AuthAuditLog(
                admin_id=admin.id,
                action="admin_mfa_failed",
                request_ip=_client_ip(request),
            )
        )
        if challenge.mfa_attempts >= MAX_MFA_FAILURES:
            challenge.revoked_at = datetime.now(UTC)
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid verification code.")
    now = datetime.now(UTC)
    challenge.is_mfa_verified = True
    challenge.expires_at = now + timedelta(hours=get_settings().admin_session_hours)
    challenge.last_seen_at = now
    db.add(
        AuthAuditLog(
            admin_id=admin.id,
            action="admin_login",
            request_ip=_client_ip(request),
        )
    )
    db.commit()
    _set_admin_cookies(
        response,
        request.cookies[ADMIN_SESSION_COOKIE],
        request.cookies[ADMIN_CSRF_COOKIE],
        get_settings().admin_session_hours * 3600,
    )
    return AdminResponse(
        id=str(admin.id),
        username=admin.username,
        email=admin.email,
        role=admin.role,
    )


@auth_router.post("/logout", response_model=MessageResponse)
def admin_logout(
    request: Request,
    response: Response,
    auth_session: AuthSession = Depends(get_admin_session_with_csrf),
    db: Session = Depends(get_db),
) -> MessageResponse:
    auth_session.revoked_at = datetime.now(UTC)
    db.add(
        AuthAuditLog(
            admin_id=auth_session.admin_id,
            action="admin_logout",
            request_ip=_client_ip(request),
        )
    )
    db.commit()
    response.delete_cookie(ADMIN_SESSION_COOKIE, path="/", secure=get_settings().cookies_are_secure, samesite="none")
    response.delete_cookie(ADMIN_CSRF_COOKIE, path="/", secure=get_settings().cookies_are_secure, samesite="none")
    return MessageResponse(message="You have been signed out.")


@auth_router.get("/me", response_model=AdminResponse)
def admin_me(
    auth_session: AuthSession = Depends(get_admin_session),
    db: Session = Depends(get_db),
) -> AdminResponse:
    admin = db.get(AdminAccount, auth_session.admin_id)
    if admin is None:
        raise HTTPException(status_code=401, detail="Session expired or invalid.")
    return AdminResponse(id=str(admin.id), username=admin.username, email=admin.email, role=admin.role)


@admin_router.get("/dashboard")
def admin_dashboard(
    auth_session: AuthSession = Depends(get_admin_session),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    admin = db.get(AdminAccount, auth_session.admin_id)
    if admin is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    if admin.role not in {"owner", "admin", "manager"}:
        raise HTTPException(status_code=403, detail="This role cannot access the admin dashboard.")
    return {"status": "ok", "admin": admin.username}


@admin_router.get(
    "/dashboard/vehicle-stats",
    response_model=AdminVehicleDashboardResponse,
)
def admin_vehicle_dashboard(
    auth_session: AuthSession = Depends(get_admin_session),
    db: Session = Depends(get_db),
) -> AdminVehicleDashboardResponse:
    if db.get_bind().dialect.name == "postgresql":
        db.rollback()
        db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
    admin = db.get(AdminAccount, auth_session.admin_id)
    if admin is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    if admin.role not in {"owner", "admin", "manager"}:
        raise HTTPException(status_code=403, detail="This role cannot access the admin dashboard.")

    now = datetime.now(UTC)
    business_timezone = "Asia/Kolkata"
    confirmed_bookings_query = (
        select(
            Booking,
            Vehicle,
            User,
            CustomerProfile,
            (Booking.start_at <= now).label("has_started"),
        )
        .join(Vehicle, Booking.vehicle_id == Vehicle.id)
        .join(User, Booking.customer_id == User.id)
        .outerjoin(CustomerProfile, CustomerProfile.user_id == User.id)
        .where(
            Booking.status == "confirmed",
            Booking.end_at > now,
        )
        .order_by(Booking.start_at, Booking.end_at, Booking.id)
    )
    confirmed_booking_rows = db.execute(confirmed_bookings_query).all()

    current_rentals: list[CurrentRentalItem] = []
    upcoming_bookings: list[UpcomingBookingItem] = []
    currently_rented_vehicle_ids: set[UUID] = set()
    for booking, vehicle, customer, profile, has_started in confirmed_booking_rows:
        customer_name = " ".join(
            value for value in (profile.first_name, profile.last_name) if value
        ) if profile is not None else ""
        booking_details = {
            "vehicle_id": vehicle.id,
            "vehicle_name": f"{vehicle.brand} {vehicle.model}",
            "registration_number": vehicle.registration_number,
            "customer_name": customer_name or customer.email or "Customer",
            "customer_mobile": customer.mobile,
            "booking_reference": booking.reference,
            "pickup_at": (
                booking.start_at.replace(tzinfo=UTC)
                if booking.start_at.tzinfo is None
                else booking.start_at.astimezone(UTC)
            ),
            "return_at": (
                booking.end_at.replace(tzinfo=UTC)
                if booking.end_at.tzinfo is None
                else booking.end_at.astimezone(UTC)
            ),
        }
        if has_started:
            if vehicle.id in currently_rented_vehicle_ids:
                continue
            currently_rented_vehicle_ids.add(vehicle.id)
            current_rentals.append(CurrentRentalItem(**booking_details))
        else:
            upcoming_bookings.append(
                UpcomingBookingItem(**booking_details)
            )

    has_bookable_rental_mode = (
        Vehicle.custom_trip_enabled.is_(True)
        | (
            Vehicle.hourly_rental_enabled.is_(True)
            & Vehicle.hourly_base_price.is_not(None)
        )
        | (
            Vehicle.daily_rental_enabled.is_(True)
            & Vehicle.daily_base_price.is_not(None)
        )
    )
    available_query = (
        select(Vehicle, City, VehicleCategory, PickupLocation)
        .join(City, City.id == Vehicle.city_id)
        .join(VehicleCategory, VehicleCategory.id == Vehicle.category_id)
        .join(PickupLocation, PickupLocation.id == Vehicle.pickup_location_id)
        .where(
            Vehicle.is_active.is_(True),
            Vehicle.availability_status == "available",
            City.is_active.is_(True),
            VehicleCategory.is_active.is_(True),
            PickupLocation.is_active.is_(True),
            PickupLocation.city_id == Vehicle.city_id,
            has_bookable_rental_mode,
        )
    )
    if currently_rented_vehicle_ids:
        available_query = available_query.where(
            ~Vehicle.id.in_(currently_rented_vehicle_ids)
        )
    available_rows = db.execute(
        available_query.order_by(
            Vehicle.brand, Vehicle.model, Vehicle.registration_number
        )
    ).all()
    available_now = [
        AvailableVehicleItem(
            vehicle_id=vehicle.id,
            vehicle_name=f"{vehicle.brand} {vehicle.model}",
            registration_number=vehicle.registration_number,
            city=city.name,
            category=category.name,
            pickup_location=location.name,
        )
        for vehicle, city, category, location in available_rows
    ]

    return AdminVehicleDashboardResponse(
        as_of=now.astimezone(ZoneInfo(business_timezone)),
        business_timezone=business_timezone,
        fleet_vehicle_count=db.scalar(select(func.count()).select_from(Vehicle)) or 0,
        currently_on_rent_count=len(current_rentals),
        currently_on_rent=current_rentals,
        upcoming_booking_count=len(upcoming_bookings),
        upcoming_bookings=upcoming_bookings,
        available_now_count=len(available_now),
        available_now=available_now,
    )
