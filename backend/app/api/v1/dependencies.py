import hashlib
import hmac
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.auth import AdminAccount, AuthSession, User
from app.services.security import hash_token

CUSTOMER_SESSION_COOKIE = "lnr_customer_session"
ADMIN_SESSION_COOKIE = "lnr_admin_session"
CUSTOMER_CSRF_COOKIE = "lnr_customer_csrf"
ADMIN_CSRF_COOKIE = "lnr_admin_csrf"


def _session_from_cookie(
    request: Request,
    db: Session,
    cookie_name: str,
    *,
    admin: bool,
    require_mfa: bool = True,
) -> AuthSession:
    token = request.cookies.get(cookie_name)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    auth_session = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
    now = datetime.now(UTC)
    expiry = auth_session.expires_at if auth_session else None
    if expiry is not None and expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    if (
        auth_session is None
        or auth_session.revoked_at is not None
        or expiry is None
        or expiry <= now
        or (admin and (auth_session.admin_id is None or (require_mfa and not auth_session.is_mfa_verified)))
        or (not admin and auth_session.user_id is None)
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired or invalid.")
    return auth_session


def get_customer_session(
    request: Request, db: Session = Depends(get_db)
) -> AuthSession:
    token = request.cookies.get(CUSTOMER_SESSION_COOKIE)
    if token:
        prior_session = db.scalar(
            select(AuthSession).where(AuthSession.token_hash == hash_token(token))
        )
        customer = (
            db.get(User, prior_session.user_id)
            if prior_session is not None and prior_session.user_id is not None
            else None
        )
        if customer is not None and customer.status == "blocked":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This customer account is blocked. Contact support.",
            )
    auth_session = _session_from_cookie(request, db, CUSTOMER_SESSION_COOKIE, admin=False)
    user = db.get(User, auth_session.user_id)
    if user is None or user.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired or invalid.")
    return auth_session


def get_admin_session(
    request: Request, db: Session = Depends(get_db)
) -> AuthSession:
    auth_session = _session_from_cookie(request, db, ADMIN_SESSION_COOKIE, admin=True)
    admin = db.get(AdminAccount, auth_session.admin_id)
    if admin is None or admin.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired or invalid.")
    return auth_session


def get_admin_challenge_session(
    request: Request, db: Session = Depends(get_db)
) -> AuthSession:
    auth_session = _session_from_cookie(
        request, db, ADMIN_SESSION_COOKIE, admin=True, require_mfa=False
    )
    admin = db.get(AdminAccount, auth_session.admin_id)
    if admin is None or admin.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired or invalid.")
    return auth_session


def require_csrf(request: Request, auth_session: AuthSession) -> None:
    csrf_cookie = ADMIN_CSRF_COOKIE if auth_session.admin_id is not None else CUSTOMER_CSRF_COOKIE
    cookie_value = request.cookies.get(csrf_cookie, "")
    header_value = request.headers.get("x-csrf-token", "")
    expected_hash = hashlib.sha256(cookie_value.encode("utf-8")).hexdigest()
    if (
        not cookie_value
        or not header_value
        or not hmac.compare_digest(cookie_value, header_value)
        or not hmac.compare_digest(expected_hash, auth_session.csrf_token_hash)
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed.")


def expose_csrf_token(request: Request, response: Response, auth_session: AuthSession) -> None:
    csrf_cookie = ADMIN_CSRF_COOKIE if auth_session.admin_id is not None else CUSTOMER_CSRF_COOKIE
    cookie_value = request.cookies.get(csrf_cookie, "")
    if cookie_value and hmac.compare_digest(
        hashlib.sha256(cookie_value.encode("utf-8")).hexdigest(),
        auth_session.csrf_token_hash,
    ):
        response.headers["X-CSRF-Token"] = cookie_value


def get_customer_session_with_csrf(
    request: Request, auth_session: AuthSession = Depends(get_customer_session)
) -> AuthSession:
    require_csrf(request, auth_session)
    return auth_session


def get_admin_session_with_csrf(
    request: Request, auth_session: AuthSession = Depends(get_admin_session)
) -> AuthSession:
    require_csrf(request, auth_session)
    return auth_session


def get_admin_challenge_with_csrf(
    request: Request, auth_session: AuthSession = Depends(get_admin_challenge_session)
) -> AuthSession:
    require_csrf(request, auth_session)
    return auth_session
