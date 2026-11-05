import html
import json
import re
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.orm import Session, joinedload

from app.core.config import get_settings
from app.models.auth import User
from app.models.bookings import (
    Booking,
    BookingEmailJob,
    BookingEvent,
    BookingNotification,
)
from app.models.vehicles import Vehicle

CUSTOMER_NOTIFICATION_EVENTS = {
    "requested": ("Booking request received", "Your booking request is pending confirmation."),
    "confirmed": ("Booking confirmed", "Your booking has been confirmed."),
    "rejected": ("Booking request rejected", "Your booking request was rejected."),
    "cancelled": ("Booking cancelled", "Your booking was cancelled."),
    "expired": ("Booking request expired", "Your pending booking request expired."),
    "offline_advance_recorded": ("Payment update", "An offline payment was recorded for your booking."),
    "advance_waived": ("Payment update", "The booking advance requirement was updated."),
    "online_advance_partial": ("Payment update", "A payment update was recorded for your booking."),
    "payment_refund_review": ("Payment update", "Your payment is under review. Please contact support."),
}
EMAIL_ADDRESS_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
INDIA_TIMEZONE = ZoneInfo("Asia/Kolkata")


def create_booking_notification(
    event: BookingEvent, booking: Booking
) -> BookingNotification | None:
    content = CUSTOMER_NOTIFICATION_EVENTS.get(event.action)
    if content is None:
        return None
    title, message = content
    return BookingNotification(
        source_event_id=event.id,
        booking_id=booking.id,
        customer_id=booking.customer_id,
        event_type=event.action,
        title=title,
        message=f"{message} Reference: {booking.reference}.",
    )


def create_booking_email_jobs(
    db: Session, event: BookingEvent, booking: Booking
) -> None:
    if event.action not in CUSTOMER_NOTIFICATION_EVENTS:
        return
    customer = db.get(User, booking.customer_id)
    db.add(
        BookingEmailJob(
            source_event_id=event.id,
            booking_id=booking.id,
            recipient_type="customer",
            recipient_email=customer.email if customer else None,
            status="pending",
        )
    )
    if event.action == "requested":
        db.add(
            BookingEmailJob(
                source_event_id=event.id,
                booking_id=booking.id,
                recipient_type="admin",
                recipient_email=get_settings().booking_admin_email,
                status="pending",
            )
        )


def _send_brevo_email(
    *,
    api_key: str,
    sender_email: str,
    sender_name: str,
    recipient: str,
    subject: str,
    text_content: str,
    html_content: str,
) -> None:
    payload = {
        "sender": {"name": sender_name, "email": sender_email},
        "to": [{"email": recipient}],
        "subject": subject,
        "textContent": text_content,
        "htmlContent": html_content,
    }
    request = Request(
        "https://api.brevo.com/v3/smtp/email",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "accept": "application/json",
            "api-key": api_key,
            "content-type": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=10) as response:
        if not 200 <= response.status < 300:
            raise URLError(f"Brevo returned HTTP {response.status}.")


def _is_valid_email_address(value: str | None) -> bool:
    return bool(value and EMAIL_ADDRESS_PATTERN.fullmatch(value))


def _format_booking_datetime(value: datetime) -> str:
    aware_value = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware_value.astimezone(INDIA_TIMEZONE).strftime("%d %b %Y, %I:%M %p IST")


def _email_content(
    job: BookingEmailJob,
    booking: Booking,
    event: BookingEvent,
    notification: BookingNotification | None,
) -> tuple[str, str, str]:
    vehicle_name = f"{booking.vehicle.brand} {booking.vehicle.model}"
    if job.recipient_type == "admin":
        customer_name = " ".join(
            part for part in (
                booking.customer.profile.first_name if booking.customer and booking.customer.profile else None,
                booking.customer.profile.last_name if booking.customer and booking.customer.profile else None,
            ) if part
        ) or "Customer"
        customer_mobile = (
            booking.customer.mobile
            if booking.customer and booking.customer.mobile
            else "Unavailable"
        )
        category_name = (
            booking.vehicle.category.name
            if booking.vehicle.category
            else "Unavailable"
        )
        pickup_location_name = (
            booking.pickup_location.name
            if booking.pickup_location and booking.pickup_location.name
            else "Unavailable"
        )
        subject = f"New booking request · {booking.reference}"
        text_content = (
            f"A customer submitted a booking request.\n"
            f"Reference: {booking.reference}\n"
            f"Customer: {customer_name}\n"
            f"Mobile: {customer_mobile}\n"
            f"Vehicle: {vehicle_name}\n"
            f"Category: {category_name}\n"
            f"Pickup location: {pickup_location_name}\n"
            f"Pickup: {_format_booking_datetime(booking.start_at)}\n"
            f"Return: {_format_booking_datetime(booking.end_at)}\n"
            f"Status: {booking.status}"
        )
        html_content = "<p>" + "<br>".join(
            html.escape(line) for line in text_content.splitlines()
        ) + "</p>"
        return subject, text_content, html_content

    title, message = CUSTOMER_NOTIFICATION_EVENTS[event.action]
    reference = booking.reference
    text_content = f"{message} Reference: {reference}.\nVehicle: {vehicle_name}"
    html_content = (
        f"<p>{html.escape(message)} Reference: {html.escape(reference)}.</p>"
        f"<p>Vehicle: {html.escape(vehicle_name)}</p>"
    )
    if notification is not None:
        title = notification.title
    return f"{title} · {reference}", text_content, html_content


def _mirror_customer_email_status(
    db: Session, job: BookingEmailJob, status: str, error: str | None
) -> None:
    if job.recipient_type != "customer":
        return
    db.execute(
        update(BookingNotification)
        .where(BookingNotification.source_event_id == job.source_event_id)
        .values(
            email_status=status,
            email_error=error,
            email_attempts=job.attempts,
            email_last_attempt_at=job.last_attempt_at,
            email_sent_at=job.provider_accepted_at,
        )
    )


def dispatch_booking_emails(db: Session, booking_id: object | None = None) -> None:
    settings = get_settings()
    pending = list(
        db.scalars(
            select(BookingEmailJob)
            .where(BookingEmailJob.status == "pending")
            .where(
                BookingEmailJob.booking_id == booking_id
                if booking_id is not None
                else True
            )
            .order_by(BookingEmailJob.created_at)
        )
    )
    for job in pending:
        api_key = settings.brevo_api_key
        sender_email = settings.brevo_sender_email
        sender_name = settings.brevo_sender_name
        recipient_email = job.recipient_email
        missing_configuration = (
            not api_key or not sender_email or not sender_name or not recipient_email
            or not _is_valid_email_address(sender_email)
            or not _is_valid_email_address(recipient_email)
        )
        if missing_configuration:
            job.status = "not_configured"
            job.error = (
                "Booking admin email is not configured."
                if job.recipient_type == "admin" and not job.recipient_email
                else "Brevo sender or recipient configuration is incomplete or invalid."
            )
            _mirror_customer_email_status(db, job, job.status, job.error)
            db.commit()
            continue

        booking = db.scalar(
            select(Booking)
            .options(
                joinedload(Booking.vehicle).joinedload(Vehicle.category),
                joinedload(Booking.pickup_location),
                joinedload(Booking.customer).joinedload(User.profile),
            )
            .where(Booking.id == job.booking_id)
        )
        if booking is None:
            job.status = "failed"
            job.error = "Booking record is unavailable."
            _mirror_customer_email_status(db, job, job.status, job.error)
            db.commit()
            continue
        notification = db.scalar(
            select(BookingNotification).where(
                BookingNotification.source_event_id == job.source_event_id
            )
        )
        event = db.get(BookingEvent, job.source_event_id)
        if event is None:
            job.status = "failed"
            job.error = "Booking event is unavailable."
            _mirror_customer_email_status(db, job, job.status, job.error)
            db.commit()
            continue

        now = datetime.now(UTC)
        claim = db.execute(
            update(BookingEmailJob)
            .where(BookingEmailJob.id == job.id, BookingEmailJob.status == "pending")
            .values(
                status="sending",
                attempts=BookingEmailJob.attempts + 1,
                last_attempt_at=now,
                error=None,
            )
        )
        if not claim.rowcount:
            db.rollback()
            continue
        db.commit()
        db.refresh(job)

        subject, text_content, html_content = _email_content(
            job, booking, event, notification
        )
        try:
            _send_brevo_email(
                api_key=api_key,
                sender_email=sender_email,
                sender_name=sender_name,
                recipient=recipient_email,
                subject=subject,
                text_content=text_content,
                html_content=html_content,
            )
        except HTTPError as exc:
            final_status = "failed" if 400 <= exc.code < 500 else "delivery_unknown"
            final_error = f"Brevo returned HTTP {exc.code}."
        except (URLError, TimeoutError, OSError) as exc:
            final_status = "delivery_unknown"
            final_error = f"Brevo connection failed ({type(exc).__name__})."
        else:
            final_status = "accepted_by_provider"
            final_error = None

        job.status = final_status
        job.error = final_error
        job.provider_accepted_at = datetime.now(UTC) if final_status == "accepted_by_provider" else None
        _mirror_customer_email_status(db, job, final_status, final_error)
        db.commit()
