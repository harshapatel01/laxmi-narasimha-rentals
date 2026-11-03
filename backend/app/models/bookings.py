from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint(
            "end_at > start_at",
            name="ck_booking_valid_time_range",
        ),
        CheckConstraint(
            "rental_type IN ('hourly', 'daily', 'custom_trip')",
            name="ck_booking_rental_type",
        ),
        CheckConstraint(
            "driving_mode IN ('self_drive', 'with_driver')",
            name="ck_booking_driving_mode",
        ),
        CheckConstraint(
            "status IN ('pending', 'awaiting_payment', 'confirmed', 'rejected', "
            "'cancelled', 'completed', 'expired')",
            name="ck_booking_status",
        ),
        CheckConstraint(
            "payment_status IN ('unpaid', 'partial', 'offline_paid', 'waived', 'online_paid', "
            "'refund_review')",
            name="ck_booking_payment_status",
        ),
        CheckConstraint(
            "confirmation_method IS NULL OR confirmation_method IN "
            "('online_advance', 'admin_manual')",
            name="ck_booking_confirmation_method",
        ),
        CheckConstraint("advance_amount >= 0", name="ck_booking_advance_nonnegative"),
        CheckConstraint("amount_paid >= 0", name="ck_booking_paid_nonnegative"),
        CheckConstraint(
            "remaining_balance >= 0",
            name="ck_booking_balance_nonnegative",
        ),
        Index("ix_bookings_vehicle_status_dates", "vehicle_id", "status", "start_at", "end_at"),
        Index("ix_bookings_customer_created", "customer_id", "created_at"),
        Index("ix_bookings_status_created", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    reference: Mapped[str] = mapped_column(String(24), unique=True, nullable=False, index=True)
    customer_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    vehicle_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("vehicles.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    city_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("cities.id", ondelete="RESTRICT"), nullable=False
    )
    pickup_location_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("pickup_locations.id", ondelete="RESTRICT"), nullable=False
    )
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rental_type: Mapped[str] = mapped_column(String(20), nullable=False)
    driving_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    estimated_total: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    hourly_rate_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    daily_rate_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    advance_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    amount_paid: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00"), nullable=False
    )
    remaining_balance: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(24), default="pending", nullable=False)
    payment_status: Mapped[str] = mapped_column(String(24), default="unpaid", nullable=False)
    confirmation_method: Mapped[str | None] = mapped_column(String(24))
    customer_notes: Mapped[str | None] = mapped_column(Text)
    admin_notes: Mapped[str | None] = mapped_column(Text)
    custom_trip_details: Mapped[str | None] = mapped_column(Text)
    licence_verification_status: Mapped[str] = mapped_column(
        String(24), default="not_required", nullable=False
    )
    confirmed_by_admin_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("admin_accounts.id", ondelete="SET NULL")
    )
    confirmation_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    customer = relationship("User")
    vehicle = relationship("Vehicle")
    city = relationship("City")
    pickup_location = relationship("PickupLocation")
    confirmed_by_admin = relationship("AdminAccount")
    events: Mapped[list["BookingEvent"]] = relationship(
        back_populates="booking", cascade="all, delete-orphan", order_by="BookingEvent.created_at"
    )
    payments: Mapped[list["BookingPayment"]] = relationship(
        back_populates="booking", cascade="all, delete-orphan", order_by="BookingPayment.created_at"
    )


class BookingEvent(Base):
    __tablename__ = "booking_status_history"
    __table_args__ = (
        Index("ix_booking_history_booking_created", "booking_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    booking_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False
    )
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_user_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL")
    )
    actor_admin_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("admin_accounts.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(24))
    to_status: Mapped[str | None] = mapped_column(String(24))
    note: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    booking: Mapped[Booking] = relationship(back_populates="events")


class BookingPayment(Base):
    __tablename__ = "booking_payments"
    __table_args__ = (
        CheckConstraint(
            "amount > 0",
            name="ck_booking_payment_amount_positive",
        ),
        CheckConstraint(
            "payment_method IN ('online', 'cash', 'upi', 'bank_transfer', 'waived')",
            name="ck_booking_payment_method",
        ),
        CheckConstraint(
            "status IN ('pending', 'verified', 'failed', 'refund_required', 'waived')",
            name="ck_booking_payment_record_status",
        ),
        Index("ix_booking_payments_booking_created", "booking_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    booking_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    payment_method: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(40))
    provider_reference: Mapped[str | None] = mapped_column(String(160), unique=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(160), unique=True)
    reference_note: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recorded_by_admin_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("admin_accounts.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    booking: Mapped[Booking] = relationship(back_populates="payments")


class BookingNotification(Base):
    __tablename__ = "booking_notifications"
    __table_args__ = (
        Index("ix_booking_notifications_customer_created", "customer_id", "created_at"),
        Index("ix_booking_notifications_email_status", "email_status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    source_event_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("booking_status_history.id", ondelete="CASCADE"),
        unique=True, nullable=False,
    )
    booking_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_status: Mapped[str] = mapped_column(
        String(24), default="pending", nullable=False
    )
    email_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    email_error: Mapped[str | None] = mapped_column(Text)
    email_last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class BookingEmailJob(Base):
    __tablename__ = "booking_email_jobs"
    __table_args__ = (
        CheckConstraint(
            "recipient_type IN ('customer', 'admin')",
            name="ck_booking_email_job_recipient_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'sending', 'accepted_by_provider', 'delivery_unknown', "
            "'failed', 'not_configured')",
            name="ck_booking_email_job_status",
        ),
        UniqueConstraint(
            "source_event_id", "recipient_type", name="uq_booking_email_job_event_recipient"
        ),
        Index("ix_booking_email_job_status_created", "status", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    source_event_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("booking_status_history.id", ondelete="CASCADE"), nullable=False
    )
    booking_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False
    )
    recipient_type: Mapped[str] = mapped_column(String(16), nullable=False)
    recipient_email: Mapped[str | None] = mapped_column(String(254))
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
