from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.dependencies import (
    get_admin_session,
    get_admin_session_with_csrf,
    get_customer_session,
    get_customer_session_with_csrf,
)
from app.api.v1.bookings import _require_booking_admin
from app.db.session import get_db
from app.models.auth import AuthSession
from app.models.bookings import Booking, BookingEmailJob, BookingEvent, BookingNotification
from app.schemas.notifications import BookingEmailJobResponse
from app.schemas.notifications import CustomerNotificationResponse, EmailNotificationResponse
from app.services.booking_notifications import dispatch_booking_emails

router = APIRouter(tags=["notifications"])
admin_router = APIRouter(prefix="/admin/bookings/notifications", tags=["admin notifications"])


def _customer_notification_response(
    notification: BookingNotification, booking: Booking
) -> CustomerNotificationResponse:
    return CustomerNotificationResponse(
        id=notification.id,
        booking_id=booking.id,
        booking_reference=booking.reference,
        event_type=notification.event_type,
        title=notification.title,
        message=notification.message,
        read_at=notification.read_at,
        created_at=notification.created_at,
    )


@router.get("/notifications", response_model=list[CustomerNotificationResponse])
def list_customer_notifications(
    session: AuthSession = Depends(get_customer_session),
    db: Session = Depends(get_db),
) -> list[CustomerNotificationResponse]:
    rows = db.execute(
        select(BookingNotification, Booking)
        .join(Booking, Booking.id == BookingNotification.booking_id)
        .where(
            BookingNotification.customer_id == session.user_id,
            Booking.customer_id == session.user_id,
        )
        .order_by(BookingNotification.created_at.desc())
        .limit(100)
    ).all()
    return [_customer_notification_response(notification, booking) for notification, booking in rows]


@router.get("/notifications/unread-count")
def unread_notification_count(
    session: AuthSession = Depends(get_customer_session),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    count = db.scalar(
        select(func.count(BookingNotification.id))
        .join(Booking, Booking.id == BookingNotification.booking_id)
        .where(
            BookingNotification.customer_id == session.user_id,
            Booking.customer_id == session.user_id,
            BookingNotification.read_at.is_(None),
        )
    )
    return {"unread_count": count or 0}


@router.post("/notifications/{notification_id}/read", response_model=CustomerNotificationResponse)
def mark_notification_read(
    notification_id: UUID,
    session: AuthSession = Depends(get_customer_session_with_csrf),
    db: Session = Depends(get_db),
) -> CustomerNotificationResponse:
    notification = db.scalar(
        select(BookingNotification)
        .join(Booking, Booking.id == BookingNotification.booking_id)
        .where(
            BookingNotification.id == notification_id,
            BookingNotification.customer_id == session.user_id,
            Booking.customer_id == session.user_id,
        )
    )
    if notification is None:
        raise HTTPException(status_code=404, detail="Notification not found.")
    if notification.read_at is None:
        notification.read_at = datetime.now(UTC)
        db.commit()
    booking = db.get(Booking, notification.booking_id)
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found.")
    return _customer_notification_response(notification, booking)


def _email_notification_response(
    notification: BookingNotification, booking: Booking
) -> EmailNotificationResponse:
    return EmailNotificationResponse(
        id=notification.id,
        booking_id=booking.id,
        booking_reference=booking.reference,
        event_type=notification.event_type,
        email_status=(
            "accepted_by_provider"
            if notification.email_status == "sent"
            else notification.email_status
        ),
        email_attempts=notification.email_attempts,
        email_error=notification.email_error,
        email_last_attempt_at=notification.email_last_attempt_at,
        email_provider_accepted_at=notification.email_sent_at,
    )


def _booking_email_job_response(
    job: BookingEmailJob, booking: Booking, event: BookingEvent
) -> BookingEmailJobResponse:
    return BookingEmailJobResponse(
        id=job.id,
        booking_id=booking.id,
        booking_reference=booking.reference,
        event_type=event.action,
        recipient_type=job.recipient_type,
        status=job.status,
        attempts=job.attempts,
        error=job.error,
        last_attempt_at=job.last_attempt_at,
        provider_accepted_at=job.provider_accepted_at,
    )


@admin_router.get("/email", response_model=list[EmailNotificationResponse])
def list_email_notifications(
    status_filter: str | None = Query(default=None, alias="status", pattern="^(pending|sending|sent|accepted_by_provider|failed|delivery_unknown|not_configured)$"),
    session: AuthSession = Depends(get_admin_session),
    db: Session = Depends(get_db),
) -> list[EmailNotificationResponse]:
    _require_booking_admin(db, session)
    query = (
        select(BookingNotification, Booking)
        .join(Booking, Booking.id == BookingNotification.booking_id)
        .order_by(BookingNotification.created_at.desc())
        .limit(100)
    )
    if status_filter:
        query = query.where(BookingNotification.email_status == status_filter)
    rows = db.execute(query).all()
    return [_email_notification_response(notification, booking) for notification, booking in rows]


@admin_router.post("/email/{notification_id}/retry", response_model=EmailNotificationResponse)
def retry_email_notification(
    notification_id: UUID,
    session: AuthSession = Depends(get_admin_session_with_csrf),
    db: Session = Depends(get_db),
) -> EmailNotificationResponse:
    _require_booking_admin(db, session)
    notification = db.get(BookingNotification, notification_id)
    if notification is None:
        raise HTTPException(status_code=404, detail="Email notification not found.")
    job = db.scalar(
        select(BookingEmailJob).where(
            BookingEmailJob.source_event_id == notification.source_event_id,
            BookingEmailJob.recipient_type == "customer",
        )
    )
    if job is None or job.status not in {"failed", "not_configured", "delivery_unknown"}:
        raise HTTPException(
            status_code=409,
            detail="No eligible customer email job is available for retry.",
        )
    job.status = "pending"
    job.error = None
    notification.email_status = "pending"
    notification.email_error = None
    booking_id = notification.booking_id
    db.commit()
    dispatch_booking_emails(db, booking_id)
    db.refresh(notification)
    booking = db.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found.")
    return _email_notification_response(notification, booking)


@admin_router.get("/email-jobs", response_model=list[BookingEmailJobResponse])
def list_booking_email_jobs(
    status_filter: str | None = Query(
        default=None,
        alias="status",
        pattern="^(pending|sending|accepted_by_provider|failed|delivery_unknown|not_configured)$",
    ),
    session: AuthSession = Depends(get_admin_session),
    db: Session = Depends(get_db),
) -> list[BookingEmailJobResponse]:
    _require_booking_admin(db, session)
    query = (
        select(BookingEmailJob, Booking, BookingEvent)
        .join(Booking, Booking.id == BookingEmailJob.booking_id)
        .join(BookingEvent, BookingEvent.id == BookingEmailJob.source_event_id)
        .order_by(BookingEmailJob.created_at.desc())
        .limit(100)
    )
    if status_filter:
        query = query.where(BookingEmailJob.status == status_filter)
    rows = db.execute(query).all()
    return [
        _booking_email_job_response(job, booking, event)
        for job, booking, event in rows
    ]


@admin_router.post(
    "/email-jobs/{job_id}/retry", response_model=BookingEmailJobResponse
)
def retry_booking_email_job(
    job_id: UUID,
    session: AuthSession = Depends(get_admin_session_with_csrf),
    db: Session = Depends(get_db),
) -> BookingEmailJobResponse:
    _require_booking_admin(db, session)
    job = db.get(BookingEmailJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Email job not found.")
    if job.status == "sending":
        last_attempt = job.last_attempt_at
        if last_attempt is None:
            raise HTTPException(
                status_code=409,
                detail="Email attempt state is incomplete; inspect the job before retrying.",
            )
        if last_attempt.tzinfo is None:
            last_attempt = last_attempt.replace(tzinfo=UTC)
        if datetime.now(UTC) - last_attempt < timedelta(minutes=10):
            raise HTTPException(
                status_code=409,
                detail="Email delivery is still being processed.",
            )
        job.status = "delivery_unknown"
    if job.status not in {"failed", "not_configured", "delivery_unknown"}:
        raise HTTPException(
            status_code=409,
            detail="This email job is not eligible for manual retry.",
        )
    job.status = "pending"
    job.error = None
    booking_id = job.booking_id
    db.commit()
    dispatch_booking_emails(db, booking_id)
    db.refresh(job)
    booking = db.get(Booking, booking_id)
    event = db.get(BookingEvent, job.source_event_id)
    if booking is None or event is None:
        raise HTTPException(status_code=404, detail="Email job event is unavailable.")
    return _booking_email_job_response(job, booking, event)
