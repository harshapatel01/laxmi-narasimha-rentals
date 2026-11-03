import math
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.models.auth import CustomerProfile, User
from app.models.bookings import Booking, BookingEvent, BookingPayment, utc_now
from app.models.vehicles import City, PickupLocation, Vehicle, VehicleCategory
from app.schemas.auth import normalize_indian_mobile
from app.schemas.bookings import BookingCreate, ManualBookingCreate
from app.services.booking_notifications import (
    create_booking_email_jobs,
    create_booking_notification,
    dispatch_booking_emails,
)

PENDING_REQUEST_LIFETIME = timedelta(hours=48)
CENT = Decimal("0.01")


@dataclass(frozen=True)
class VerifiedOnlinePayment:
    """Payment data returned only after a provider adapter verifies its signature."""

    booking_id: UUID
    amount: Decimal
    provider: str
    provider_reference: str
    idempotency_key: str


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def booking_query():
    return (
        select(Booking)
        .options(
            joinedload(Booking.customer).joinedload(User.profile),
            joinedload(Booking.vehicle),
            joinedload(Booking.city),
            joinedload(Booking.pickup_location),
            joinedload(Booking.events),
            joinedload(Booking.payments),
        )
        .execution_options(populate_existing=True)
    )


def get_booking_with_details(db: Session, booking_id: UUID) -> Booking | None:
    return db.execute(
        booking_query().where(Booking.id == booking_id)
    ).unique().scalar_one_or_none()


def add_booking_event(
    db: Session,
    booking: Booking,
    *,
    actor_type: str,
    action: str,
    from_status: str | None,
    to_status: str | None,
    actor_user_id: UUID | None = None,
    actor_admin_id: UUID | None = None,
    note: str | None = None,
    details: dict | None = None,
) -> None:
    event = BookingEvent(
        booking_id=booking.id,
        actor_type=actor_type,
        actor_user_id=actor_user_id,
        actor_admin_id=actor_admin_id,
        action=action,
        from_status=from_status,
        to_status=to_status,
        note=note,
        details=details,
    )
    db.add(event)
    db.flush()
    notification = create_booking_notification(event, booking)
    if notification is not None:
        db.add(notification)
        create_booking_email_jobs(db, event, booking)


def expire_stale_bookings(db: Session) -> None:
    now = utc_now()
    stale = list(
        db.scalars(
            select(Booking)
            .where(
                Booking.status.in_(("pending", "awaiting_payment")),
                Booking.expires_at <= now,
            )
            .with_for_update(skip_locked=True)
        )
    )
    for booking in stale:
        old_status = booking.status
        booking.status = "expired"
        add_booking_event(
            db,
            booking,
            actor_type="system",
            action="expired",
            from_status=old_status,
            to_status="expired",
            note="Unconfirmed request expired after 48 hours.",
        )
    if stale:
        db.flush()


def lock_vehicle(db: Session, vehicle_id: UUID) -> Vehicle:
    vehicle = db.scalar(
        select(Vehicle).where(Vehicle.id == vehicle_id).with_for_update()
    )
    if vehicle is None:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    return vehicle


def validate_vehicle_booking(
    db: Session,
    vehicle: Vehicle,
    *,
    start_at: datetime,
    end_at: datetime,
    rental_type: str,
    driving_mode: str,
    pickup_location_id: UUID | None = None,
    ignore_booking_id: UUID | None = None,
) -> None:
    if not vehicle.is_active or vehicle.availability_status != "available":
        raise HTTPException(status_code=409, detail="This vehicle is not available for booking.")
    city = db.get(City, vehicle.city_id)
    category = db.get(VehicleCategory, vehicle.category_id)
    location = db.get(
        PickupLocation, pickup_location_id or vehicle.pickup_location_id
    )
    if city is None or not city.is_active or category is None or not category.is_active:
        raise HTTPException(status_code=409, detail="This vehicle is not currently bookable.")
    if (
        location is None
        or not location.is_active
        or location.city_id != vehicle.city_id
    ):
        raise HTTPException(status_code=409, detail="Vehicle pickup location is not available.")
    if driving_mode == "self_drive" and not vehicle.self_drive_enabled:
        raise HTTPException(status_code=422, detail="Self-drive is not supported by this vehicle.")
    if driving_mode == "with_driver" and not vehicle.with_driver_enabled:
        raise HTTPException(status_code=422, detail="With-driver rental is not supported by this vehicle.")
    if rental_type == "hourly" and not vehicle.hourly_rental_enabled:
        raise HTTPException(status_code=422, detail="Hourly rental is not supported by this vehicle.")
    if rental_type == "daily" and not vehicle.daily_rental_enabled:
        raise HTTPException(status_code=422, detail="Daily rental is not supported by this vehicle.")
    if rental_type == "custom_trip" and not vehicle.custom_trip_enabled:
        raise HTTPException(status_code=422, detail="Custom-trip rental is not supported by this vehicle.")
    overlap_query = select(Booking.id).where(
        Booking.vehicle_id == vehicle.id,
        Booking.status == "confirmed",
        Booking.start_at < end_at,
        Booking.end_at > start_at,
    )
    if ignore_booking_id is not None:
        overlap_query = overlap_query.where(Booking.id != ignore_booking_id)
    if db.scalar(overlap_query.limit(1)) is not None:
        raise HTTPException(
            status_code=409,
            detail="This vehicle is unavailable for your selected dates and times.",
        )


def estimate_total(vehicle: Vehicle, start_at: datetime, end_at: datetime, rental_type: str) -> Decimal | None:
    if rental_type == "custom_trip":
        return None
    duration_seconds = Decimal(str((end_at - start_at).total_seconds()))
    if rental_type == "hourly":
        rate = vehicle.hourly_base_price
        units = math.ceil(duration_seconds / Decimal(3600))
    else:
        rate = vehicle.daily_base_price
        units = math.ceil(duration_seconds / Decimal(86400))
    if rate is None:
        raise HTTPException(status_code=422, detail="Rental pricing is not configured for this vehicle.")
    return (rate * units).quantize(CENT)


def create_customer_booking(
    db: Session, customer_id: UUID, payload: BookingCreate
) -> tuple[Booking, bool]:
    expire_stale_bookings(db)
    now = utc_now()
    start_at = _as_utc(payload.start_at)
    end_at = _as_utc(payload.end_at)
    if start_at <= now:
        raise HTTPException(status_code=422, detail="Pickup date and time must be in the future.")
    vehicle = lock_vehicle(db, payload.vehicle_id)
    validate_vehicle_booking(
        db,
        vehicle,
        start_at=start_at,
        end_at=end_at,
        rental_type=payload.rental_type,
        driving_mode=payload.driving_mode,
        pickup_location_id=payload.pickup_location_id,
    )
    user = db.get(User, customer_id)
    if user is None or user.status != "active":
        raise HTTPException(status_code=401, detail="Authentication required.")
    try:
        normalize_indian_mobile(user.mobile)
    except ValueError as exc:
        raise HTTPException(
            status_code=403,
            detail="Add a valid Indian mobile number to your account before booking.",
        ) from exc
    requested_pickup_location_id = payload.pickup_location_id or vehicle.pickup_location_id
    customer_notes = (payload.customer_notes or "").strip() or None
    custom_trip_details = (payload.custom_trip_details or "").strip() or None
    existing_request = db.scalar(
        select(Booking)
        .where(
            Booking.customer_id == customer_id,
            Booking.vehicle_id == vehicle.id,
            Booking.pickup_location_id == requested_pickup_location_id,
            Booking.start_at == start_at,
            Booking.end_at == end_at,
            Booking.rental_type == payload.rental_type,
            Booking.driving_mode == payload.driving_mode,
            Booking.customer_notes == customer_notes,
            Booking.custom_trip_details == custom_trip_details,
            Booking.status.in_(("pending", "awaiting_payment")),
            Booking.expires_at > now,
        )
        .order_by(Booking.created_at.desc())
        .limit(1)
    )
    if existing_request is not None:
        db.commit()
        return get_booking_with_details(db, existing_request.id), False

    total = estimate_total(vehicle, start_at, end_at, payload.rental_type)
    booking = Booking(
        reference=f"LNR-{now:%y%m%d}-{secrets.token_hex(3).upper()}",
        customer_id=customer_id,
        vehicle_id=vehicle.id,
        city_id=vehicle.city_id,
        pickup_location_id=requested_pickup_location_id,
        start_at=start_at,
        end_at=end_at,
        rental_type=payload.rental_type,
        driving_mode=payload.driving_mode,
        estimated_total=total,
        hourly_rate_snapshot=vehicle.hourly_base_price if payload.rental_type == "hourly" else None,
        daily_rate_snapshot=vehicle.daily_base_price if payload.rental_type == "daily" else None,
        advance_amount=vehicle.advance_payment_amount,
        amount_paid=Decimal("0.00"),
        remaining_balance=total or Decimal("0.00"),
        status="pending",
        payment_status="unpaid",
        customer_notes=customer_notes,
        custom_trip_details=custom_trip_details,
        licence_verification_status=(
            "pending_review" if payload.driving_mode == "self_drive" else "not_required"
        ),
        expires_at=now + PENDING_REQUEST_LIFETIME,
    )
    db.add(booking)
    db.flush()
    add_booking_event(
        db,
        booking,
        actor_type="customer",
        actor_user_id=customer_id,
        action="requested",
        from_status=None,
        to_status="pending",
    )
    db.commit()
    dispatch_booking_emails(db, booking.id)
    return get_booking_with_details(db, booking.id), True


def _lock_booking_for_vehicle(db: Session, booking_id: UUID) -> tuple[Booking, Vehicle]:
    preliminary = db.get(Booking, booking_id)
    if preliminary is None:
        raise HTTPException(status_code=404, detail="Booking not found.")
    vehicle = lock_vehicle(db, preliminary.vehicle_id)
    booking = db.scalar(
        select(Booking)
        .where(Booking.id == booking_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found.")
    return booking, vehicle


def confirm_booking(
    db: Session,
    booking_id: UUID,
    *,
    admin_id: UUID | None,
    method: str,
    note: str | None = None,
) -> Booking:
    booking, vehicle = _lock_booking_for_vehicle(db, booking_id)
    expire_stale_bookings(db)
    db.refresh(booking)
    _confirm_booking_locked(
        db,
        booking,
        vehicle,
        admin_id=admin_id,
        method=method,
        note=note,
    )
    db.commit()
    dispatch_booking_emails(db, booking.id)
    return get_booking_with_details(db, booking.id)


def _confirm_booking_locked(
    db: Session,
    booking: Booking,
    vehicle: Vehicle,
    *,
    admin_id: UUID | None,
    method: str,
    note: str | None,
) -> None:
    if booking.status not in {"pending", "awaiting_payment"}:
        raise HTTPException(status_code=409, detail=f"Booking cannot be confirmed from {booking.status}.")
    if _as_utc(booking.expires_at) <= utc_now():
        raise HTTPException(status_code=409, detail="Booking request has expired.")
    if method not in {"admin_manual", "online_advance"}:
        raise ValueError("Unsupported confirmation method.")
    if method == "online_advance" and booking.amount_paid < booking.advance_amount:
        raise HTTPException(status_code=409, detail="Verified online advance payment is required.")
    validate_vehicle_booking(
        db,
        vehicle,
        start_at=booking.start_at,
        end_at=booking.end_at,
        rental_type=booking.rental_type,
        driving_mode=booking.driving_mode,
        pickup_location_id=booking.pickup_location_id,
        ignore_booking_id=booking.id,
    )
    previous_status = booking.status
    booking.status = "confirmed"
    booking.confirmation_method = method
    booking.confirmed_by_admin_id = admin_id
    booking.confirmation_note = note
    booking.confirmed_at = utc_now()
    if booking.estimated_total is not None:
        booking.remaining_balance = max(
            Decimal("0.00"), booking.estimated_total - booking.amount_paid
        )
    add_booking_event(
        db,
        booking,
        actor_type="admin" if admin_id else "system",
        actor_admin_id=admin_id,
        action="confirmed",
        from_status=previous_status,
        to_status="confirmed",
        note=note,
        details={"confirmation_method": method},
    )


def transition_booking(
    db: Session,
    booking_id: UUID,
    *,
    target_status: str,
    admin_id: UUID | None = None,
    customer_id: UUID | None = None,
    note: str | None = None,
) -> Booking:
    booking, _ = _lock_booking_for_vehicle(db, booking_id)
    if customer_id is not None and booking.customer_id != customer_id:
        raise HTTPException(status_code=404, detail="Booking not found.")
    expire_stale_bookings(db)
    db.refresh(booking)
    allowed = {
        "rejected": {"pending", "awaiting_payment"},
        "cancelled": {"pending", "awaiting_payment", "confirmed"},
        "completed": {"confirmed"},
    }
    if booking.status not in allowed.get(target_status, set()):
        raise HTTPException(
            status_code=409,
            detail=f"Booking cannot transition from {booking.status} to {target_status}.",
        )
    if customer_id is not None and (
        booking.customer_id != customer_id or target_status != "cancelled"
        or booking.status == "confirmed"
    ):
        raise HTTPException(status_code=403, detail="This booking cannot be cancelled by the customer.")
    previous_status = booking.status
    booking.status = target_status
    if target_status == "cancelled":
        booking.cancelled_at = utc_now()
    add_booking_event(
        db,
        booking,
        actor_type="customer" if customer_id else "admin",
        actor_user_id=customer_id,
        actor_admin_id=admin_id,
        action=target_status,
        from_status=previous_status,
        to_status=target_status,
        note=note,
    )
    db.commit()
    dispatch_booking_emails(db, booking.id)
    return get_booking_with_details(db, booking.id)


def record_offline_advance(
    db: Session,
    booking_id: UUID,
    *,
    admin_id: UUID,
    amount: Decimal,
    payment_method: str,
    reference_note: str | None,
    notes: str | None = None,
    received_at: datetime | None = None,
) -> Booking:
    booking, _ = _lock_booking_for_vehicle(db, booking_id)
    if booking.status not in {"pending", "awaiting_payment", "confirmed"}:
        raise HTTPException(status_code=409, detail="An advance cannot be recorded for this booking.")
    if booking.payment_status == "waived":
        raise HTTPException(status_code=409, detail="The advance has already been waived.")
    if amount > booking.advance_amount - booking.amount_paid:
        raise HTTPException(status_code=422, detail="Advance payment exceeds the outstanding advance amount.")
    previous_status = booking.status
    payment = BookingPayment(
        booking_id=booking.id,
        amount=amount,
        payment_method=payment_method,
        status="verified",
        reference_note=reference_note,
        notes=(notes or "").strip() or None,
        paid_at=_as_utc(received_at) if received_at else utc_now(),
        recorded_by_admin_id=admin_id,
    )
    db.add(payment)
    booking.amount_paid += amount
    if booking.estimated_total is not None:
        booking.remaining_balance = max(
            Decimal("0.00"), booking.estimated_total - booking.amount_paid
        )
    if booking.amount_paid >= booking.advance_amount:
        booking.payment_status = "offline_paid"
    elif booking.amount_paid > 0:
        booking.payment_status = "partial"
    add_booking_event(
        db,
        booking,
        actor_type="admin",
        actor_admin_id=admin_id,
        action="offline_advance_recorded",
        from_status=previous_status,
        to_status=booking.status,
        note=reference_note,
        details={"amount": str(amount), "payment_method": payment_method},
    )
    db.commit()
    dispatch_booking_emails(db, booking.id)
    return get_booking_with_details(db, booking.id)


def waive_advance(
    db: Session, booking_id: UUID, *, admin_id: UUID, reason: str
) -> Booking:
    booking, _ = _lock_booking_for_vehicle(db, booking_id)
    if booking.status not in {"pending", "awaiting_payment", "confirmed"}:
        raise HTTPException(status_code=409, detail="The advance cannot be waived for this booking.")
    if booking.payment_status in {"offline_paid", "online_paid", "waived"}:
        raise HTTPException(status_code=409, detail="The advance has already been settled.")
    old_status = booking.payment_status
    booking.payment_status = "waived"
    outstanding_advance = booking.advance_amount - booking.amount_paid
    if outstanding_advance > 0:
        db.add(
            BookingPayment(
                booking_id=booking.id,
                amount=outstanding_advance,
                payment_method="waived",
                status="waived",
                reference_note=reason,
                recorded_by_admin_id=admin_id,
            )
        )
    add_booking_event(
        db,
        booking,
        actor_type="admin",
        actor_admin_id=admin_id,
        action="advance_waived",
        from_status=booking.status,
        to_status=booking.status,
        note=reason,
        details={"previous_payment_status": old_status},
    )
    db.commit()
    dispatch_booking_emails(db, booking.id)
    return get_booking_with_details(db, booking.id)


def set_custom_trip_quotation(
    db: Session,
    booking_id: UUID,
    *,
    admin_id: UUID,
    amount: Decimal,
    note: str | None,
) -> Booking:
    booking, _ = _lock_booking_for_vehicle(db, booking_id)
    if booking.rental_type != "custom_trip":
        raise HTTPException(status_code=409, detail="A quotation is only available for custom trips.")
    if booking.status not in {"pending", "awaiting_payment"}:
        raise HTTPException(status_code=409, detail="A quotation cannot be changed for this booking.")
    previous_total = booking.estimated_total
    booking.estimated_total = amount
    booking.remaining_balance = max(Decimal("0.00"), amount - booking.amount_paid)
    add_booking_event(
        db,
        booking,
        actor_type="admin",
        actor_admin_id=admin_id,
        action="custom_trip_quotation_set",
        from_status=booking.status,
        to_status=booking.status,
        note=note,
        details={
            "previous_total": str(previous_total) if previous_total is not None else None,
            "quoted_total": str(amount),
        },
    )
    db.commit()
    return get_booking_with_details(db, booking.id)


def process_verified_online_payment(db: Session, payment: VerifiedOnlinePayment) -> Booking:
    """Apply a payment only after an external adapter has authenticated the provider event."""
    booking, vehicle = _lock_booking_for_vehicle(db, payment.booking_id)
    duplicate = db.scalar(
        select(BookingPayment).where(
            or_(
                BookingPayment.idempotency_key == payment.idempotency_key,
                BookingPayment.provider_reference == payment.provider_reference,
            )
        )
    )
    if duplicate is not None:
        duplicate_booking_id = duplicate.booking_id
        if (
            duplicate_booking_id != booking.id
            or duplicate.amount != payment.amount
            or duplicate.provider != payment.provider
        ):
            db.rollback()
            raise HTTPException(status_code=409, detail="Payment reference was already used.")
        db.rollback()
        return get_booking_with_details(db, duplicate_booking_id)
    if payment.amount <= 0 or payment.amount > booking.advance_amount - booking.amount_paid:
        raise HTTPException(status_code=422, detail="Verified payment amount is invalid.")
    can_confirm = (
        booking.status in {"pending", "awaiting_payment"}
        and _as_utc(booking.expires_at) > utc_now()
        and vehicle.is_active
        and vehicle.availability_status == "available"
    )
    if can_confirm:
        try:
            validate_vehicle_booking(
                db,
                vehicle,
                start_at=booking.start_at,
                end_at=booking.end_at,
                rental_type=booking.rental_type,
                driving_mode=booking.driving_mode,
                pickup_location_id=booking.pickup_location_id,
                ignore_booking_id=booking.id,
            )
        except HTTPException:
            can_confirm = False
    payment_record = BookingPayment(
        booking_id=booking.id,
        amount=payment.amount,
        payment_method="online",
        status="verified" if can_confirm else "refund_required",
        provider=payment.provider,
        provider_reference=payment.provider_reference,
        idempotency_key=payment.idempotency_key,
        paid_at=utc_now(),
    )
    db.add(payment_record)
    booking.amount_paid += payment.amount
    if booking.estimated_total is not None:
        booking.remaining_balance = max(
            Decimal("0.00"), booking.estimated_total - booking.amount_paid
        )
    if can_confirm:
        if booking.amount_paid >= booking.advance_amount:
            booking.payment_status = "online_paid"
            _confirm_booking_locked(
                db,
                booking,
                vehicle,
                admin_id=None,
                method="online_advance",
                note=None,
            )
        else:
            booking.payment_status = "partial"
            add_booking_event(
                db,
                booking,
                actor_type="system",
                action="online_advance_partial",
                from_status=booking.status,
                to_status=booking.status,
                details={"amount": str(payment.amount)},
            )
    else:
        booking.payment_status = "refund_review"
        add_booking_event(
            db,
            booking,
            actor_type="system",
            action="payment_refund_review",
            from_status=booking.status,
            to_status=booking.status,
            note="Payment verified after booking availability was lost or request expired.",
        )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        duplicate = db.scalar(
            select(BookingPayment).where(
                or_(
                    BookingPayment.idempotency_key == payment.idempotency_key,
                    BookingPayment.provider_reference == payment.provider_reference,
                )
            )
        )
        if duplicate is None:
            raise
        if (
            duplicate.booking_id != payment.booking_id
            or duplicate.amount != payment.amount
            or duplicate.provider != payment.provider
        ):
            raise HTTPException(status_code=409, detail="Payment reference was already used.")
        return get_booking_with_details(db, duplicate.booking_id)
    dispatch_booking_emails(db, booking.id)
    return get_booking_with_details(db, booking.id)


def create_manual_booking(
    db: Session,
    payload: ManualBookingCreate,
    *,
    admin_id: UUID,
) -> Booking:
    mobile = normalize_indian_mobile(payload.mobile)
    customer = db.scalar(select(User).where(User.mobile == mobile))
    if customer is None:
        customer = User(mobile=mobile, status="active")
        db.add(customer)
        db.flush()
        db.add(CustomerProfile(user_id=customer.id))
        db.flush()
    now = utc_now()
    start_at = _as_utc(payload.start_at)
    end_at = _as_utc(payload.end_at)
    if start_at <= now:
        raise HTTPException(status_code=422, detail="Pickup date and time must be in the future.")
    vehicle = lock_vehicle(db, payload.vehicle_id)
    validate_vehicle_booking(
        db,
        vehicle,
        start_at=start_at,
        end_at=end_at,
        rental_type=payload.rental_type,
        driving_mode=payload.driving_mode,
    )
    total = estimate_total(vehicle, start_at, end_at, payload.rental_type)
    booking = Booking(
        reference=f"LNR-{now:%y%m%d}-{secrets.token_hex(3).upper()}",
        customer_id=customer.id,
        vehicle_id=vehicle.id,
        city_id=vehicle.city_id,
        pickup_location_id=vehicle.pickup_location_id,
        start_at=start_at,
        end_at=end_at,
        rental_type=payload.rental_type,
        driving_mode=payload.driving_mode,
        estimated_total=total,
        hourly_rate_snapshot=vehicle.hourly_base_price if payload.rental_type == "hourly" else None,
        daily_rate_snapshot=vehicle.daily_base_price if payload.rental_type == "daily" else None,
        advance_amount=vehicle.advance_payment_amount,
        amount_paid=Decimal("0.00"),
        remaining_balance=total or Decimal("0.00"),
        status="pending",
        payment_status="unpaid",
        customer_notes=payload.customer_notes,
        custom_trip_details=payload.custom_trip_details,
        licence_verification_status=(
            "pending_review" if payload.driving_mode == "self_drive" else "not_required"
        ),
        expires_at=now + PENDING_REQUEST_LIFETIME,
    )
    db.add(booking)
    db.flush()
    add_booking_event(
        db,
        booking,
        actor_type="admin",
        actor_admin_id=admin_id,
        action="manual_request_created",
        from_status=None,
        to_status="pending",
    )
    return confirm_booking(
        db,
        booking.id,
        admin_id=admin_id,
        method="admin_manual",
        note=payload.confirmation_note,
    )
