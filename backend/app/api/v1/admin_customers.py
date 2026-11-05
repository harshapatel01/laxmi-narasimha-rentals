from datetime import UTC, datetime, timedelta
from uuid import UUID

from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, selectinload

from app.api.v1.bookings import booking_response
from app.api.v1.dependencies import get_admin_session, get_admin_session_with_csrf
from app.db.session import get_db
from app.models.auth import AdminAccount, AuthAuditLog, AuthSession, CustomerProfile, User
from app.models.bookings import Booking
from app.schemas.auth import (
    AdminCustomerResponse,
    AdminCustomerStatusChange,
    AdminSensitiveActionRequest,
)
from app.schemas.bookings import BookingResponse
from app.services.bookings import booking_query
from app.services.security import password_hasher

router = APIRouter(prefix="/admin/customers", tags=["admin customer management"])
PASSWORD_FAILURE_WINDOW = timedelta(minutes=15)
MAX_PASSWORD_FAILURES = 5
ADMIN_ROLES = {"owner", "admin", "manager"}


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _require_customer_manager(db: Session, admin_id: UUID | None) -> AdminAccount:
    if admin_id is None:
        raise HTTPException(status_code=401, detail="Authentication required.")
    admin = db.get(AdminAccount, admin_id)
    if admin is None or admin.status != "active":
        raise HTTPException(status_code=401, detail="Authentication required.")
    if admin.role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="This role cannot manage customers.")
    return admin


def _customer_response(user: User) -> AdminCustomerResponse:
    profile = user.profile
    name = None
    if profile is not None:
        name = " ".join(
            part for part in (profile.first_name, profile.last_name) if part
        ) or None
    return AdminCustomerResponse(
        id=str(user.id),
        full_name=name,
        email=user.email,
        mobile=user.mobile,
        status=user.status,
        created_at=user.created_at,
    )


def _verify_admin_password(
    db: Session,
    admin: AdminAccount,
    request: Request,
    password: str,
) -> None:
    now = datetime.now(UTC)
    request_ip = _client_ip(request)
    recent_failures = db.scalar(
        select(func.count())
        .select_from(AuthAuditLog)
        .where(
            AuthAuditLog.action == "admin_customer_password_failed",
            or_(
                AuthAuditLog.admin_id == admin.id,
                AuthAuditLog.request_ip == request_ip,
            ),
            AuthAuditLog.created_at >= now - PASSWORD_FAILURE_WINDOW,
        )
    ) or 0
    if recent_failures >= MAX_PASSWORD_FAILURES:
        raise HTTPException(
            status_code=429,
            detail="Too many password confirmation attempts. Try again later.",
        )
    try:
        valid = password_hasher.verify(admin.password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        valid = False
    if not valid:
        db.add(
            AuthAuditLog(
                admin_id=admin.id,
                action="admin_customer_password_failed",
                request_ip=request_ip,
            )
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="The administrator password is incorrect.",
        )


@router.get("", response_model=list[AdminCustomerResponse])
def list_customers(
    q: str | None = Query(default=None, max_length=160),
    auth_session: AuthSession = Depends(get_admin_session),
    db: Session = Depends(get_db),
) -> list[AdminCustomerResponse]:
    _require_customer_manager(db, auth_session.admin_id)
    query = (
        select(User)
        .outerjoin(CustomerProfile, CustomerProfile.user_id == User.id)
        .options(selectinload(User.profile))
    )
    if q and q.strip():
        search = f"%{q.strip().lower()}%"
        mobile_search = "".join(character for character in q if character.isdigit())
        full_name = (
            func.coalesce(CustomerProfile.first_name, "")
            + " "
            + func.coalesce(CustomerProfile.last_name, "")
        )
        query = query.where(
            or_(
                func.lower(full_name).like(search),
                func.lower(func.coalesce(User.email, "")).like(search),
                func.lower(User.mobile).like(search),
                User.mobile.like(f"%{mobile_search}%") if mobile_search else False,
            )
        )
    customers = db.scalars(query.order_by(User.created_at.desc())).unique().all()
    return [_customer_response(customer) for customer in customers]


@router.get("/{customer_id}/bookings", response_model=list[BookingResponse])
def customer_bookings(
    customer_id: UUID,
    auth_session: AuthSession = Depends(get_admin_session),
    db: Session = Depends(get_db),
) -> list[BookingResponse]:
    _require_customer_manager(db, auth_session.admin_id)
    if db.get(User, customer_id) is None:
        raise HTTPException(status_code=404, detail="Customer not found.")
    rows = db.scalars(
        booking_query()
        .where(Booking.customer_id == customer_id)
        .order_by(Booking.created_at.desc())
    ).unique().all()
    return [booking_response(row) for row in rows]


def _change_customer_status(
    customer_id: UUID,
    payload: AdminCustomerStatusChange,
    request: Request,
    auth_session: AuthSession,
    db: Session,
    *,
    target_status: str,
) -> AdminCustomerResponse:
    admin = _require_customer_manager(db, auth_session.admin_id)
    _verify_admin_password(db, admin, request, payload.password)
    customer = db.scalar(
        select(User).where(User.id == customer_id).with_for_update()
    )
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found.")
    if customer.status in {"deactivated", "deleted"}:
        raise HTTPException(
            status_code=409,
            detail="This customer account cannot be changed through block or unblock.",
        )

    customer.status = target_status
    if target_status == "blocked":
        db.execute(
            update(AuthSession)
            .where(
                AuthSession.user_id == customer.id,
                AuthSession.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
    details = {"reason": payload.reason} if payload.reason else None
    action = "customer_blocked" if target_status == "blocked" else "customer_unblocked"
    db.add(
        AuthAuditLog(
            user_id=customer.id,
            admin_id=admin.id,
            action=action,
            request_ip=_client_ip(request),
            details=details,
        )
    )
    db.commit()
    db.refresh(customer)
    return _customer_response(customer)


@router.post("/{customer_id}/block", response_model=AdminCustomerResponse)
def block_customer(
    customer_id: UUID,
    payload: AdminCustomerStatusChange,
    request: Request,
    auth_session: AuthSession = Depends(get_admin_session_with_csrf),
    db: Session = Depends(get_db),
) -> AdminCustomerResponse:
    return _change_customer_status(
        customer_id, payload, request, auth_session, db, target_status="blocked"
    )


@router.post("/{customer_id}/unblock", response_model=AdminCustomerResponse)
def unblock_customer(
    customer_id: UUID,
    payload: AdminCustomerStatusChange,
    request: Request,
    auth_session: AuthSession = Depends(get_admin_session_with_csrf),
    db: Session = Depends(get_db),
) -> AdminCustomerResponse:
    return _change_customer_status(
        customer_id, payload, request, auth_session, db, target_status="active"
    )


@router.post("/{customer_id}/deactivate", response_model=AdminCustomerResponse)
def deactivate_customer(
    customer_id: UUID,
    payload: AdminSensitiveActionRequest,
    request: Request,
    auth_session: AuthSession = Depends(get_admin_session_with_csrf),
    db: Session = Depends(get_db),
) -> AdminCustomerResponse:
    admin = _require_customer_manager(db, auth_session.admin_id)
    _verify_admin_password(db, admin, request, payload.password)
    customer = db.scalar(
        select(User).where(User.id == customer_id).with_for_update()
    )
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found.")
    if customer.status == "deleted":
        raise HTTPException(status_code=409, detail="This customer has been deleted.")
    if customer.status == "deactivated":
        raise HTTPException(status_code=409, detail="This customer is already deactivated.")

    customer.status = "deactivated"
    now = datetime.now(UTC)
    db.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id == customer.id,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    db.add(
        AuthAuditLog(
            user_id=customer.id,
            admin_id=admin.id,
            action="customer_deactivated",
            request_ip=_client_ip(request),
            details={"reason": payload.reason} if payload.reason else None,
            created_at=now,
        )
    )
    db.commit()
    db.refresh(customer)
    return _customer_response(customer)


@router.post("/{customer_id}/reactivate", response_model=AdminCustomerResponse)
def reactivate_customer(
    customer_id: UUID,
    payload: AdminSensitiveActionRequest,
    request: Request,
    auth_session: AuthSession = Depends(get_admin_session_with_csrf),
    db: Session = Depends(get_db),
) -> AdminCustomerResponse:
    admin = _require_customer_manager(db, auth_session.admin_id)
    _verify_admin_password(db, admin, request, payload.password)
    customer = db.scalar(
        select(User).where(User.id == customer_id).with_for_update()
    )
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found.")
    if customer.status != "deactivated":
        raise HTTPException(
            status_code=409,
            detail="Only deactivated customer accounts can be reactivated.",
        )

    customer.status = "active"
    now = datetime.now(UTC)
    db.add(
        AuthAuditLog(
            user_id=customer.id,
            admin_id=admin.id,
            action="customer_reactivated",
            request_ip=_client_ip(request),
            details={"reason": payload.reason} if payload.reason else None,
            created_at=now,
        )
    )
    db.commit()
    db.refresh(customer)
    return _customer_response(customer)


@router.delete("/{customer_id}", response_model=AdminCustomerResponse)
def delete_customer(
    customer_id: UUID,
    payload: AdminSensitiveActionRequest,
    request: Request,
    auth_session: AuthSession = Depends(get_admin_session_with_csrf),
    db: Session = Depends(get_db),
) -> AdminCustomerResponse:
    admin = _require_customer_manager(db, auth_session.admin_id)
    _verify_admin_password(db, admin, request, payload.password)
    customer = db.scalar(
        select(User).where(User.id == customer_id).with_for_update()
    )
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found.")
    if customer.status == "deleted":
        raise HTTPException(status_code=409, detail="This customer is already deleted.")

    customer.status = "deleted"
    now = datetime.now(UTC)
    db.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id == customer.id,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    db.add(
        AuthAuditLog(
            user_id=customer.id,
            admin_id=admin.id,
            action="customer_deleted",
            request_ip=_client_ip(request),
            details={"reason": payload.reason} if payload.reason else None,
            created_at=now,
        )
    )
    db.commit()
    db.refresh(customer)
    return _customer_response(customer)
