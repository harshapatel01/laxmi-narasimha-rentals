from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.v1.dependencies import (
    get_admin_session,
    get_admin_session_with_csrf,
    get_customer_session,
    get_customer_session_with_csrf,
)
from app.db.session import get_db
from app.models.auth import AdminAccount, AuthSession, CustomerProfile, User
from app.models.bookings import Booking
from app.models.vehicles import Vehicle
from app.services.booking_notifications import dispatch_booking_emails
from app.services.whatsapp_cloud import send_booking_request_notification
from app.schemas.bookings import (
    AdminBookingAction,
    AvailabilityResponse,
    BookingCreate,
    BookingDetailResponse,
    BookingNotesInput,
    BookingQuotationInput,
    BookingResponse,
    BookingEventResponse,
    ManualBookingCreate,
    OfflineAdvanceInput,
    WaiveAdvanceInput,
)
from app.services.bookings import (
    add_booking_event,
    booking_query,
    confirm_booking,
    create_customer_booking,
    create_manual_booking,
    estimate_total,
    expire_stale_bookings,
    get_booking_with_details,
    record_offline_advance,
    set_custom_trip_quotation,
    transition_booking,
    validate_vehicle_booking,
    waive_advance,
)

router = APIRouter(tags=["bookings"])
admin_router = APIRouter(prefix="/admin/bookings", tags=["admin bookings"])
BOOKING_ADMIN_ROLES = {"owner", "admin", "manager"}


def _require_booking_admin(db: Session, session: AuthSession) -> None:
    if session.admin_id is None:
        raise HTTPException(status_code=401, detail="Admin authentication required.")
    admin = db.get(AdminAccount, session.admin_id)
    if admin is None or admin.status != "active":
        raise HTTPException(status_code=401, detail="Admin authentication required.")
    if admin.role not in BOOKING_ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="This role cannot manage bookings.")


def _customer_name(booking: Booking) -> str | None:
    profile = booking.customer.profile
    if profile is None:
        return None
    name = " ".join(
        part for part in (profile.first_name, profile.last_name) if part
    )
    return name or None


def booking_response(
    booking: Booking, *, include_admin_notes: bool = False
) -> BookingResponse:
    return BookingResponse(
        id=booking.id,
        reference=booking.reference,
        vehicle_id=booking.vehicle_id,
        vehicle_name=f"{booking.vehicle.brand} {booking.vehicle.model}",
        vehicle_code=booking.vehicle.vehicle_code,
        customer_id=booking.customer_id,
        customer_mobile=booking.customer.mobile,
        customer_name=_customer_name(booking),
        city_id=booking.city_id,
        city_name=booking.city.name,
        pickup_location_id=booking.pickup_location_id,
        pickup_location_name=booking.pickup_location.name,
        pickup_address=booking.pickup_location.address,
        start_at=booking.start_at,
        end_at=booking.end_at,
        rental_type=booking.rental_type,
        driving_mode=booking.driving_mode,
        estimated_total=booking.estimated_total,
        hourly_rate_snapshot=booking.hourly_rate_snapshot,
        daily_rate_snapshot=booking.daily_rate_snapshot,
        advance_amount=booking.advance_amount,
        amount_paid=booking.amount_paid,
        remaining_balance=booking.remaining_balance,
        status=booking.status,
        payment_status=booking.payment_status,
        confirmation_method=booking.confirmation_method,
        customer_notes=booking.customer_notes,
        admin_notes=booking.admin_notes if include_admin_notes else None,
        custom_trip_details=booking.custom_trip_details,
        licence_verification_status=booking.licence_verification_status,
        confirmed_by_admin_id=booking.confirmed_by_admin_id,
        confirmation_note=booking.confirmation_note if include_admin_notes else None,
        expires_at=booking.expires_at,
        created_at=booking.created_at,
        confirmed_at=booking.confirmed_at,
        cancelled_at=booking.cancelled_at,
    )


def booking_detail(
    booking: Booking, *, include_internal: bool = False
) -> BookingDetailResponse:
    data = booking_response(booking, include_admin_notes=include_internal).model_dump()
    return BookingDetailResponse(
        **data,
        events=[
            BookingEventResponse(
                id=event.id,
                actor_type=event.actor_type,
                action=event.action,
                from_status=event.from_status,
                to_status=event.to_status,
                note=event.note if include_internal or event.actor_type != "admin" else None,
                created_at=event.created_at,
            )
            for event in booking.events
        ],
        payments=booking.payments,
    )


@router.get(
    "/vehicles/{vehicle_id}/availability",
    response_model=AvailabilityResponse,
    tags=["vehicles"],
)
def vehicle_availability(
    vehicle_id: UUID,
    start_at: datetime,
    end_at: datetime,
    pickup_location_id: UUID | None = None,
    rental_type: str = Query(pattern="^(hourly|daily|custom_trip)$"),
    driving_mode: str = Query(pattern="^(self_drive|with_driver)$"),
    db: Session = Depends(get_db),
) -> AvailabilityResponse:
    if start_at.tzinfo is None or end_at.tzinfo is None or end_at <= start_at:
        raise HTTPException(
            status_code=422,
            detail="Provide timezone-aware pickup and return date/times in the correct order.",
        )
    if start_at.astimezone(UTC) <= datetime.now(UTC):
        raise HTTPException(status_code=422, detail="Pickup date and time must be in the future.")
    vehicle = db.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    try:
        validate_vehicle_booking(
            db,
            vehicle,
            start_at=start_at,
            end_at=end_at,
            rental_type=rental_type,
            driving_mode=driving_mode,
            pickup_location_id=pickup_location_id,
        )
    except HTTPException as exc:
        if exc.status_code == 409:
            return AvailabilityResponse(
                available=False,
                estimated_total=None,
                advance_amount=vehicle.advance_payment_amount,
                hourly_rate=vehicle.hourly_base_price,
                daily_rate=vehicle.daily_base_price,
                message=exc.detail,
            )
        raise
    return AvailabilityResponse(
        available=True,
        estimated_total=estimate_total(vehicle, start_at, end_at, rental_type),
        advance_amount=vehicle.advance_payment_amount,
        hourly_rate=vehicle.hourly_base_price,
        daily_rate=vehicle.daily_base_price,
    )


@router.post("/bookings", response_model=BookingResponse, status_code=status.HTTP_201_CREATED)
def create_booking(
    payload: BookingCreate,
    session: AuthSession = Depends(get_customer_session_with_csrf),
    db: Session = Depends(get_db),
) -> BookingResponse:
    booking, created = create_customer_booking(db, session.user_id, payload)
    if created:
        send_booking_request_notification(booking)
    return booking_response(booking)


@router.get("/bookings/me", response_model=list[BookingResponse])
def my_bookings(
    session: AuthSession = Depends(get_customer_session),
    db: Session = Depends(get_db),
) -> list[BookingResponse]:
    expire_stale_bookings(db)
    db.commit()
    rows = db.scalars(
        booking_query()
        .where(Booking.customer_id == session.user_id)
        .order_by(Booking.created_at.desc())
    ).unique().all()
    return [booking_response(row) for row in rows]


@router.get("/bookings/{booking_id}", response_model=BookingDetailResponse)
def get_my_booking(
    booking_id: UUID,
    session: AuthSession = Depends(get_customer_session),
    db: Session = Depends(get_db),
) -> BookingDetailResponse:
    booking = db.execute(
        booking_query().where(
            Booking.id == booking_id,
            Booking.customer_id == session.user_id,
        )
    ).unique().scalar_one_or_none()
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found.")
    return booking_detail(booking)


@router.post("/bookings/{booking_id}/cancel", response_model=BookingResponse)
def cancel_my_booking(
    booking_id: UUID,
    payload: AdminBookingAction,
    session: AuthSession = Depends(get_customer_session_with_csrf),
    db: Session = Depends(get_db),
) -> BookingResponse:
    booking = transition_booking(
        db,
        booking_id,
        target_status="cancelled",
        customer_id=session.user_id,
        note=payload.note,
    )
    return booking_response(booking)


@admin_router.get("", response_model=list[BookingResponse])
def list_bookings(
    status_filter: str | None = Query(
        default=None,
        alias="status",
        pattern="^(pending|awaiting_payment|confirmed|rejected|cancelled|completed|expired)$",
    ),
    search: str | None = Query(default=None, max_length=120),
    session: AuthSession = Depends(get_admin_session),
    db: Session = Depends(get_db),
) -> list[BookingResponse]:
    _require_booking_admin(db, session)
    if session.admin_id is None:
        raise HTTPException(status_code=401, detail="Admin authentication required.")
    expire_stale_bookings(db)
    db.commit()
    query = booking_query().order_by(Booking.created_at.desc())
    if status_filter:
        query = query.where(Booking.status == status_filter)
    if search and search.strip():
        term = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{term}%"
        query = query.where(
            or_(
                Booking.reference.ilike(pattern, escape="\\"),
                Booking.customer.has(
                    or_(
                        User.mobile.ilike(pattern, escape="\\"),
                        User.email.ilike(pattern, escape="\\"),
                        User.profile.has(
                            or_(
                                CustomerProfile.first_name.ilike(pattern, escape="\\"),
                                CustomerProfile.last_name.ilike(pattern, escape="\\"),
                            )
                        ),
                    )
                ),
                Booking.vehicle.has(
                    or_(
                        Vehicle.vehicle_code.ilike(pattern, escape="\\"),
                        Vehicle.brand.ilike(pattern, escape="\\"),
                        Vehicle.model.ilike(pattern, escape="\\"),
                    )
                ),
            )
        )
    return [
        booking_response(row, include_admin_notes=True)
        for row in db.scalars(query).unique().all()
    ]


@admin_router.get("/{booking_id}", response_model=BookingDetailResponse)
def get_admin_booking(
    booking_id: UUID,
    session: AuthSession = Depends(get_admin_session),
    db: Session = Depends(get_db),
) -> BookingDetailResponse:
    _require_booking_admin(db, session)
    if session.admin_id is None:
        raise HTTPException(status_code=401, detail="Admin authentication required.")
    booking = get_booking_with_details(db, booking_id)
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found.")
    return booking_detail(booking, include_internal=True)


@admin_router.post("/manual", response_model=BookingResponse, status_code=status.HTTP_201_CREATED)
def create_admin_manual_booking(
    payload: ManualBookingCreate,
    session: AuthSession = Depends(get_admin_session_with_csrf),
    db: Session = Depends(get_db),
) -> BookingResponse:
    _require_booking_admin(db, session)
    booking = create_manual_booking(db, payload, admin_id=session.admin_id)
    return booking_response(booking, include_admin_notes=True)


@admin_router.post("/{booking_id}/confirm", response_model=BookingResponse)
def manually_confirm_booking(
    booking_id: UUID,
    payload: AdminBookingAction,
    session: AuthSession = Depends(get_admin_session_with_csrf),
    db: Session = Depends(get_db),
) -> BookingResponse:
    _require_booking_admin(db, session)
    booking = confirm_booking(
        db,
        booking_id,
        admin_id=session.admin_id,
        method="admin_manual",
        note=payload.note,
    )
    dispatch_booking_emails(db, booking.id)
    return booking_response(booking, include_admin_notes=True)


@admin_router.post("/{booking_id}/reject", response_model=BookingResponse)
def reject_booking(
    booking_id: UUID,
    payload: AdminBookingAction,
    session: AuthSession = Depends(get_admin_session_with_csrf),
    db: Session = Depends(get_db),
) -> BookingResponse:
    _require_booking_admin(db, session)
    if not (payload.note or "").strip():
        raise HTTPException(status_code=422, detail="Provide a reason for rejecting the booking.")
    booking = transition_booking(
        db,
        booking_id,
        target_status="rejected",
        admin_id=session.admin_id,
        note=payload.note,
    )
    dispatch_booking_emails(db, booking.id)
    return booking_response(booking, include_admin_notes=True)


@admin_router.post("/{booking_id}/cancel", response_model=BookingResponse)
def admin_cancel_booking(
    booking_id: UUID,
    payload: AdminBookingAction,
    session: AuthSession = Depends(get_admin_session_with_csrf),
    db: Session = Depends(get_db),
) -> BookingResponse:
    _require_booking_admin(db, session)
    booking = transition_booking(
        db,
        booking_id,
        target_status="cancelled",
        admin_id=session.admin_id,
        note=payload.note,
    )
    dispatch_booking_emails(db, booking.id)
    return booking_response(booking, include_admin_notes=True)


@admin_router.post("/{booking_id}/complete", response_model=BookingResponse)
def complete_booking(
    booking_id: UUID,
    payload: AdminBookingAction,
    session: AuthSession = Depends(get_admin_session_with_csrf),
    db: Session = Depends(get_db),
) -> BookingResponse:
    _require_booking_admin(db, session)
    booking = transition_booking(
        db,
        booking_id,
        target_status="completed",
        admin_id=session.admin_id,
        note=payload.note,
    )
    dispatch_booking_emails(db, booking.id)
    return booking_response(booking, include_admin_notes=True)


@admin_router.post("/{booking_id}/offline-advance", response_model=BookingResponse)
def add_offline_advance(
    booking_id: UUID,
    payload: OfflineAdvanceInput,
    session: AuthSession = Depends(get_admin_session_with_csrf),
    db: Session = Depends(get_db),
) -> BookingResponse:
    _require_booking_admin(db, session)
    if payload.received_at is not None and payload.received_at.tzinfo is None:
        raise HTTPException(status_code=422, detail="Payment date/time must include a timezone.")
    booking = record_offline_advance(
        db,
        booking_id,
        admin_id=session.admin_id,
        amount=payload.amount,
        payment_method=payload.payment_method,
        reference_note=payload.reference_note,
        notes=payload.notes,
        received_at=payload.received_at,
    )
    dispatch_booking_emails(db, booking.id)
    return booking_response(booking, include_admin_notes=True)


@admin_router.post("/{booking_id}/waive-advance", response_model=BookingResponse)
def waive_booking_advance(
    booking_id: UUID,
    payload: WaiveAdvanceInput,
    session: AuthSession = Depends(get_admin_session_with_csrf),
    db: Session = Depends(get_db),
) -> BookingResponse:
    _require_booking_admin(db, session)
    booking = waive_advance(
        db,
        booking_id,
        admin_id=session.admin_id,
        reason=payload.reason,
    )
    dispatch_booking_emails(db, booking.id)
    return booking_response(booking, include_admin_notes=True)


@admin_router.patch("/{booking_id}/notes", response_model=BookingResponse)
def update_booking_notes(
    booking_id: UUID,
    payload: BookingNotesInput,
    session: AuthSession = Depends(get_admin_session_with_csrf),
    db: Session = Depends(get_db),
) -> BookingResponse:
    _require_booking_admin(db, session)
    booking = db.scalar(
        select(Booking).where(Booking.id == booking_id).with_for_update()
    )
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found.")
    booking.admin_notes = payload.admin_notes
    add_booking_event(
        db,
        booking,
        actor_type="admin",
        actor_admin_id=session.admin_id,
        action="admin_note_updated",
        from_status=booking.status,
        to_status=booking.status,
        note=payload.admin_notes,
    )
    db.commit()
    result = get_booking_with_details(db, booking.id)
    return booking_response(result, include_admin_notes=True)


@admin_router.post("/{booking_id}/quotation", response_model=BookingResponse)
def quote_custom_trip(
    booking_id: UUID,
    payload: BookingQuotationInput,
    session: AuthSession = Depends(get_admin_session_with_csrf),
    db: Session = Depends(get_db),
) -> BookingResponse:
    _require_booking_admin(db, session)
    booking = set_custom_trip_quotation(
        db,
        booking_id,
        admin_id=session.admin_id,
        amount=payload.amount,
        note=payload.note,
    )
    return booking_response(booking, include_admin_notes=True)
