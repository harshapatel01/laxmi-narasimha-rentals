import hashlib
import logging
import secrets
import smtplib
from email.message import EmailMessage
from datetime import UTC, datetime, timedelta
from uuid import UUID

from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.dependencies import (
    CUSTOMER_CSRF_COOKIE,
    CUSTOMER_SESSION_COOKIE,
    expose_csrf_token,
    get_customer_session,
    get_customer_session_with_csrf,
)
from app.core.config import get_settings
from app.db.session import get_db, get_session_factory
from app.models.auth import (
    AuthAuditLog,
    AuthSession,
    CustomerPasswordResetToken,
    CustomerProfile,
    User,
)
from app.schemas.auth import (
    CustomerResponse,
    CustomerCredentialSetupRequest,
    CustomerLoginRequest,
    CustomerProfileUpdate,
    CustomerRegistrationRequest,
    MessageResponse,
    PasswordResetConfirm,
    PasswordResetRequest,
)
from app.services.security import (
    hash_token,
    new_session_tokens,
    password_hasher,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["customer authentication"])
GENERIC_RESET_MESSAGE = "If an account can be reset, password reset instructions will be emailed."
MAX_CUSTOMER_LOGIN_FAILURES = 5
MAX_CUSTOMER_IP_FAILURES = 20
MAX_CUSTOMER_REGISTER_REQUESTS = 10
_dummy_password_hash = password_hasher.hash(secrets.token_urlsafe(32))


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _set_session_cookies(response: Response, token: str, csrf_token: str, max_age: int) -> None:
    settings = get_settings()
    response.headers["X-CSRF-Token"] = csrf_token
    response.set_cookie(
        CUSTOMER_SESSION_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        secure=settings.cookies_are_secure,
        samesite="none",
        path="/",
    )
    response.set_cookie(
        CUSTOMER_CSRF_COOKIE,
        csrf_token,
        max_age=max_age,
        httponly=False,
        secure=settings.cookies_are_secure,
        samesite="none",
        path="/",
    )


def _customer_response(user: User, profile: CustomerProfile | None) -> CustomerResponse:
    return CustomerResponse(
        id=str(user.id),
        mobile=user.mobile,
        email=user.email,
        mobile_verified=user.mobile_verified,
        status=user.status,
        first_name=profile.first_name if profile else None,
        last_name=profile.last_name if profile else None,
    )


def _split_full_name(full_name: str) -> tuple[str, str | None]:
    parts = full_name.split()
    return parts[0], " ".join(parts[1:]) or None


def _create_customer_session(
    db: Session,
    user: User,
    request: Request,
    response: Response,
    *,
    action: str,
) -> CustomerResponse:
    now = datetime.now(UTC)
    prior_token = request.cookies.get(CUSTOMER_SESSION_COOKIE)
    if prior_token:
        prior_session = db.scalar(
            select(AuthSession)
            .where(AuthSession.token_hash == hash_token(prior_token))
            .with_for_update()
        )
        if (
            prior_session is not None
            and prior_session.user_id is not None
            and prior_session.revoked_at is None
        ):
            prior_session.revoked_at = now
    session_token, csrf_token = new_session_tokens()
    session_hours = get_settings().customer_session_hours
    db.add(
        AuthSession(
            user_id=user.id,
            token_hash=hash_token(session_token),
            csrf_token_hash=hashlib.sha256(csrf_token.encode("utf-8")).hexdigest(),
            expires_at=now + timedelta(hours=session_hours),
        )
    )
    db.add(
        AuthAuditLog(
            user_id=user.id,
            action=action,
            request_ip=_client_ip(request),
        )
    )
    db.commit()
    db.refresh(user)
    profile = db.scalar(select(CustomerProfile).where(CustomerProfile.user_id == user.id))
    _set_session_cookies(response, session_token, csrf_token, session_hours * 3600)
    return _customer_response(user, profile)


def _password_is_valid(password_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _smtp_is_configured() -> bool:
    settings = get_settings()
    return bool(
        settings.smtp_host
        and settings.smtp_from_email
        and settings.smtp_username
        and settings.smtp_password
    )


def _send_password_reset_email(destination: str, raw_token: str) -> None:
    settings = get_settings()
    if not _smtp_is_configured():
        raise RuntimeError("Password reset email delivery is not configured.")
    reset_url = f"{settings.frontend_origin.rstrip('/')}/password-reset/confirm?token={raw_token}"
    message = EmailMessage()
    message["Subject"] = "Reset your Laxmi Narasimha Rentals password"
    message["From"] = settings.smtp_from_email
    message["To"] = destination
    message.set_content(
        "A password reset was requested for your account. "
        f"Use this link within {settings.password_reset_token_minutes} minutes:\n\n"
        f"{reset_url}\n\nIf you did not request this, you can ignore this email."
    )
    with (
        smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=10)
        if settings.smtp_use_ssl
        else smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10)
    ) as server:
        if not settings.smtp_use_ssl:
            server.starttls()
        if settings.smtp_username and settings.smtp_password:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(message)


def _deliver_password_reset_email(
    reset_id: UUID,
    user_id: UUID,
    destination: str,
    raw_token: str,
    request_ip: str,
) -> None:
    try:
        _send_password_reset_email(destination, raw_token)
    except (OSError, smtplib.SMTPException, RuntimeError) as exc:
        with get_session_factory()() as db:
            reset = db.get(CustomerPasswordResetToken, reset_id)
            if reset is not None and reset.consumed_at is None:
                reset.consumed_at = datetime.now(UTC)
            db.add(
                AuthAuditLog(
                    user_id=user_id,
                    action="customer_password_reset_delivery_failed",
                    request_ip=request_ip,
                    details={
                        "error_type": type(exc).__name__,
                        "smtp_code": getattr(exc, "smtp_code", None),
                    },
                )
            )
            db.commit()
        logger.warning(
            "Password reset email delivery failed (error_type=%s).",
            type(exc).__name__,
        )
        return

    with get_session_factory()() as db:
        db.add(
            AuthAuditLog(
                user_id=user_id,
                action="customer_password_reset_email_accepted_by_smtp",
                request_ip=request_ip,
            )
        )
        db.commit()


def _password_reset_email_hash(email: str) -> str:
    return hash_token(f"password-reset-email:{email}")


def _password_reset_lock_id(identifier: str) -> int:
    digest = bytes.fromhex(hash_token(f"password-reset-rate:{identifier}"))
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


def _acquire_password_reset_rate_locks(db: Session, request_ip: str, email_hash: str) -> None:
    if db.get_bind().dialect.name != "postgresql":
        return
    lock_ids = sorted({
        _password_reset_lock_id(f"ip:{request_ip}"),
        _password_reset_lock_id(f"email:{email_hash}"),
    })
    for lock_id in lock_ids:
        db.execute(select(func.pg_advisory_xact_lock(lock_id)))


@router.post("/register", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
def register_customer(
    payload: CustomerRegistrationRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> CustomerResponse:
    now = datetime.now(UTC)
    recent_registrations = db.scalar(
        select(func.count()).select_from(AuthAuditLog).where(
            AuthAuditLog.action.in_(
                ("customer_registration", "customer_registration_duplicate")
            ),
            AuthAuditLog.request_ip == _client_ip(request),
            AuthAuditLog.created_at >= now - timedelta(minutes=15),
        )
    ) or 0
    if recent_registrations >= MAX_CUSTOMER_REGISTER_REQUESTS:
        raise HTTPException(status_code=429, detail="Too many registration attempts. Try again later.")
    existing = db.scalar(
        select(User).where(
            or_(
                func.lower(User.email) == payload.email,
                User.mobile == payload.mobile,
            )
        )
    )
    if existing is not None:
        db.add(
            AuthAuditLog(
                user_id=existing.id,
                action="customer_registration_duplicate",
                request_ip=_client_ip(request),
            )
        )
        db.commit()
        raise HTTPException(
            status_code=409,
            detail="An account already uses this email or mobile number. Sign in or contact support.",
        )

    first_name, last_name = _split_full_name(payload.full_name)
    user = User(
        mobile=payload.mobile,
        email=payload.email,
        password_hash=password_hasher.hash(payload.password),
        mobile_verified=False,
        status="active",
    )
    try:
        db.add(user)
        db.flush()
        profile = CustomerProfile(user_id=user.id, first_name=first_name, last_name=last_name)
        db.add(profile)
        db.flush()
        return _create_customer_session(
            db, user, request, response, action="customer_registration"
        )
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="An account already uses this email or mobile number. Sign in or contact support.",
        ) from exc


@router.post("/login", response_model=CustomerResponse)
def login_customer(
    payload: CustomerLoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> CustomerResponse:
    now = datetime.now(UTC)
    user = db.scalar(
        select(User)
        .where(func.lower(User.email) == payload.email)
        .with_for_update()
    )
    password_hash = user.password_hash if user and user.password_hash else _dummy_password_hash
    password_valid = _password_is_valid(password_hash, payload.password)
    ip_failures = db.scalar(
        select(func.count()).select_from(AuthAuditLog).where(
            AuthAuditLog.action == "customer_login_failed",
            AuthAuditLog.request_ip == _client_ip(request),
            AuthAuditLog.created_at >= now - timedelta(minutes=15),
        )
    ) or 0
    locked_until = _as_utc(user.locked_until) if user and user.locked_until else None
    locked = user is not None and (
        user.status != "active"
        or user.password_hash is None
        or (locked_until is not None and locked_until > now)
    )
    if (
        user is not None
        and user.status == "blocked"
        and password_valid
        and ip_failures < MAX_CUSTOMER_IP_FAILURES
    ):
        db.add(
            AuthAuditLog(
                user_id=user.id,
                action="customer_login_blocked",
                request_ip=_client_ip(request),
            )
        )
        db.commit()
        raise HTTPException(
            status_code=403,
            detail="This customer account is blocked. Contact support.",
        )
    if not password_valid or user is None or locked or ip_failures >= MAX_CUSTOMER_IP_FAILURES:
        if user is not None:
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= MAX_CUSTOMER_LOGIN_FAILURES:
                user.locked_until = now + timedelta(minutes=15)
        db.add(
            AuthAuditLog(
                user_id=user.id if user else None,
                action="customer_login_failed",
                request_ip=_client_ip(request),
            )
        )
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid credentials or account temporarily unavailable.")
    user.failed_login_attempts = 0
    user.locked_until = None
    return _create_customer_session(db, user, request, response, action="customer_login")


@router.post("/credentials", response_model=CustomerResponse)
def establish_customer_credentials(
    payload: CustomerCredentialSetupRequest,
    request: Request,
    response: Response,
    auth_session: AuthSession = Depends(get_customer_session_with_csrf),
    db: Session = Depends(get_db),
) -> CustomerResponse:
    user = db.scalar(select(User).where(User.id == auth_session.user_id).with_for_update())
    if user is None:
        raise HTTPException(status_code=401, detail="Session expired or invalid.")
    if user.password_hash is not None or user.email is not None:
        raise HTTPException(status_code=409, detail="Customer credentials are already established.")
    if db.scalar(select(User.id).where(func.lower(User.email) == payload.email)) is not None:
        raise HTTPException(status_code=409, detail="An account already uses this email address.")
    user.email = payload.email
    user.password_hash = password_hasher.hash(payload.password)
    profile = db.scalar(select(CustomerProfile).where(CustomerProfile.user_id == user.id))
    if profile is None:
        profile = CustomerProfile(user_id=user.id)
        db.add(profile)
    if payload.full_name:
        profile.first_name, profile.last_name = _split_full_name(payload.full_name)
    db.add(
        AuthAuditLog(
            user_id=user.id,
            action="customer_credentials_established",
            request_ip=_client_ip(request),
        )
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="An account already uses this email address.",
        ) from exc
    db.refresh(user)
    db.refresh(profile)
    return _customer_response(user, profile)


@router.post("/password-reset/request", response_model=MessageResponse, status_code=202)
def request_password_reset(
    payload: PasswordResetRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> MessageResponse:
    settings = get_settings()
    now = datetime.now(UTC)
    request_ip = _client_ip(request)
    email_hash = _password_reset_email_hash(payload.email)
    _acquire_password_reset_rate_locks(db, request_ip, email_hash)
    recent_ip_requests = db.scalar(
        select(func.count()).select_from(AuthAuditLog).where(
            AuthAuditLog.action == "customer_password_reset_requested",
            AuthAuditLog.request_ip == request_ip,
            AuthAuditLog.created_at
            >= now - timedelta(minutes=settings.password_reset_ip_window_minutes),
        )
    ) or 0
    recent_email_requests = db.scalar(
        select(func.count()).select_from(AuthAuditLog).where(
            AuthAuditLog.action == "customer_password_reset_requested",
            AuthAuditLog.details["email_hash"].as_string() == email_hash,
            AuthAuditLog.created_at
            >= now - timedelta(minutes=settings.password_reset_email_window_minutes),
        )
    ) or 0
    if (
        recent_ip_requests >= settings.password_reset_ip_limit
        or recent_email_requests >= settings.password_reset_email_limit
    ):
        db.add(
            AuthAuditLog(
                action="customer_password_reset_rate_limited",
                request_ip=request_ip,
                details={
                    "email_hash": email_hash,
                    "limit": (
                        "ip"
                        if recent_ip_requests >= settings.password_reset_ip_limit
                        else "email"
                    ),
                },
            )
        )
        db.commit()
        logger.info("Password reset request rate limit reached.")
        return MessageResponse(message=GENERIC_RESET_MESSAGE)

    db.add(
        AuthAuditLog(
            action="customer_password_reset_requested",
            request_ip=request_ip,
            details={"email_hash": email_hash},
        )
    )
    db.commit()

    if not _smtp_is_configured():
        db.add(
            AuthAuditLog(
                action="customer_password_reset_delivery_failed",
                request_ip=request_ip,
                details={
                    "email_hash": email_hash,
                    "error_type": "SMTPNotConfigured",
                },
            )
        )
        db.commit()
        logger.warning("Password reset email delivery is not configured.")
        return MessageResponse(message=GENERIC_RESET_MESSAGE)

    user = db.scalar(
        select(User).where(func.lower(User.email) == payload.email, User.status == "active")
    )
    if user is not None and user.password_hash is not None:
        raw_token = secrets.token_urlsafe(32)
        reset = CustomerPasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(raw_token),
            expires_at=now + timedelta(minutes=settings.password_reset_token_minutes),
            request_ip=request_ip,
        )
        db.add(reset)
        db.add(
            AuthAuditLog(
                user_id=user.id,
                action="customer_password_reset_issued",
                request_ip=request_ip,
            )
        )
        db.commit()
        db.refresh(reset)
        background_tasks.add_task(
            _deliver_password_reset_email,
            reset.id,
            user.id,
            user.email or payload.email,
            raw_token,
            request_ip,
        )
    return MessageResponse(message=GENERIC_RESET_MESSAGE)


@router.post("/password-reset/confirm", response_model=MessageResponse)
def confirm_password_reset(
    payload: PasswordResetConfirm,
    request: Request,
    db: Session = Depends(get_db),
) -> MessageResponse:
    now = datetime.now(UTC)
    reset = db.scalar(
        select(CustomerPasswordResetToken)
        .where(CustomerPasswordResetToken.token_hash == hash_token(payload.token))
        .with_for_update()
    )
    if (
        reset is None
        or reset.consumed_at is not None
        or _as_utc(reset.expires_at) <= now
    ):
        raise HTTPException(status_code=400, detail="Password reset link is invalid or expired.")
    user = db.scalar(select(User).where(User.id == reset.user_id).with_for_update())
    if user is None or user.status != "active":
        raise HTTPException(status_code=400, detail="Password reset link is invalid or expired.")
    reset.consumed_at = now
    user.password_hash = password_hasher.hash(payload.password)
    user.failed_login_attempts = 0
    user.locked_until = None
    db.query(AuthSession).filter(
        AuthSession.user_id == user.id,
        AuthSession.revoked_at.is_(None),
    ).update({AuthSession.revoked_at: now}, synchronize_session=False)
    db.query(CustomerPasswordResetToken).filter(
        CustomerPasswordResetToken.user_id == user.id,
        CustomerPasswordResetToken.consumed_at.is_(None),
        CustomerPasswordResetToken.id != reset.id,
    ).update({CustomerPasswordResetToken.consumed_at: now}, synchronize_session=False)
    db.add(
        AuthAuditLog(
            user_id=user.id,
            action="customer_password_reset_completed",
            request_ip=_client_ip(request),
        )
    )
    db.commit()
    return MessageResponse(message="Password updated. Sign in with your new password.")


@router.post("/logout", response_model=MessageResponse)
def customer_logout(
    request: Request,
    response: Response,
    auth_session: AuthSession = Depends(get_customer_session_with_csrf),
    db: Session = Depends(get_db),
) -> MessageResponse:
    auth_session.revoked_at = datetime.now(UTC)
    db.add(
        AuthAuditLog(
            user_id=auth_session.user_id,
            action="customer_logout",
            request_ip=_client_ip(request),
        )
    )
    db.commit()
    response.delete_cookie(CUSTOMER_SESSION_COOKIE, path="/", secure=get_settings().cookies_are_secure, samesite="none")
    response.delete_cookie(CUSTOMER_CSRF_COOKIE, path="/", secure=get_settings().cookies_are_secure, samesite="none")
    return MessageResponse(message="You have been signed out.")


@router.get("/me", response_model=CustomerResponse)
def customer_me(
    request: Request,
    response: Response,
    auth_session: AuthSession = Depends(get_customer_session),
    db: Session = Depends(get_db),
) -> CustomerResponse:
    user = db.get(User, auth_session.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Session expired or invalid.")
    profile = db.scalar(select(CustomerProfile).where(CustomerProfile.user_id == user.id))
    expose_csrf_token(request, response, auth_session)
    return _customer_response(user, profile)


@router.patch("/profile", response_model=CustomerResponse)
def update_customer_profile(
    payload: CustomerProfileUpdate,
    request: Request,
    auth_session: AuthSession = Depends(get_customer_session_with_csrf),
    db: Session = Depends(get_db),
) -> CustomerResponse:
    user = db.get(User, auth_session.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Session expired or invalid.")
    profile = db.scalar(select(CustomerProfile).where(CustomerProfile.user_id == user.id))
    if profile is None:
        profile = CustomerProfile(user_id=user.id)
        db.add(profile)
    for field in payload.model_fields_set:
        setattr(profile, field, getattr(payload, field))
    db.add(AuthAuditLog(user_id=user.id, action="customer_profile_updated", request_ip=_client_ip(request)))
    db.commit()
    db.refresh(profile)
    return _customer_response(user, profile)
