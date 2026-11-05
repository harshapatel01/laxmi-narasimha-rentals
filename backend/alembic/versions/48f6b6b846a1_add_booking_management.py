"""add booking management

Revision ID: 48f6b6b846a1
Revises: 9928220d99cc
Create Date: 2026-10-27 23:30:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "48f6b6b846a1"
down_revision: Union[str, Sequence[str], None] = "9928220d99cc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bookings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("reference", sa.String(length=24), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("vehicle_id", sa.Uuid(), nullable=False),
        sa.Column("city_id", sa.Uuid(), nullable=False),
        sa.Column("pickup_location_id", sa.Uuid(), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rental_type", sa.String(length=20), nullable=False),
        sa.Column("driving_mode", sa.String(length=20), nullable=False),
        sa.Column("estimated_total", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("hourly_rate_snapshot", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("daily_rate_snapshot", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("advance_amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("amount_paid", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("remaining_balance", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("payment_status", sa.String(length=24), nullable=False),
        sa.Column("confirmation_method", sa.String(length=24), nullable=True),
        sa.Column("customer_notes", sa.Text(), nullable=True),
        sa.Column("admin_notes", sa.Text(), nullable=True),
        sa.Column("custom_trip_details", sa.Text(), nullable=True),
        sa.Column("licence_verification_status", sa.String(length=24), nullable=False),
        sa.Column("confirmed_by_admin_id", sa.Uuid(), nullable=True),
        sa.Column("confirmation_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("end_at > start_at", name="ck_booking_valid_time_range"),
        sa.CheckConstraint(
            "rental_type IN ('hourly', 'daily', 'custom_trip')",
            name="ck_booking_rental_type",
        ),
        sa.CheckConstraint(
            "driving_mode IN ('self_drive', 'with_driver')",
            name="ck_booking_driving_mode",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'awaiting_payment', 'confirmed', 'rejected', "
            "'cancelled', 'completed', 'expired')",
            name="ck_booking_status",
        ),
        sa.CheckConstraint(
            "payment_status IN ('unpaid', 'partial', 'offline_paid', 'waived', 'online_paid', "
            "'refund_review')",
            name="ck_booking_payment_status",
        ),
        sa.CheckConstraint(
            "confirmation_method IS NULL OR confirmation_method IN "
            "('online_advance', 'admin_manual')",
            name="ck_booking_confirmation_method",
        ),
        sa.CheckConstraint("advance_amount >= 0", name="ck_booking_advance_nonnegative"),
        sa.CheckConstraint("amount_paid >= 0", name="ck_booking_paid_nonnegative"),
        sa.CheckConstraint(
            "remaining_balance >= 0",
            name="ck_booking_balance_nonnegative",
        ),
        sa.ForeignKeyConstraint(["customer_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["city_id"], ["cities.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["pickup_location_id"], ["pickup_locations.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by_admin_id"], ["admin_accounts.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bookings_reference", "bookings", ["reference"], unique=True)
    op.create_index("ix_bookings_customer_id", "bookings", ["customer_id"], unique=False)
    op.create_index("ix_bookings_vehicle_id", "bookings", ["vehicle_id"], unique=False)
    op.create_index(
        "ix_bookings_vehicle_status_dates",
        "bookings",
        ["vehicle_id", "status", "start_at", "end_at"],
    )
    op.create_index(
        "ix_bookings_customer_created", "bookings", ["customer_id", "created_at"]
    )
    op.create_index(
        "ix_bookings_status_created", "bookings", ["status", "created_at"]
    )

    op.create_table(
        "booking_status_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("booking_id", sa.Uuid(), nullable=False),
        sa.Column("actor_type", sa.String(length=16), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("actor_admin_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("from_status", sa.String(length=24), nullable=True),
        sa.Column("to_status", sa.String(length=24), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["booking_id"], ["bookings.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["actor_admin_id"], ["admin_accounts.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_booking_history_booking_created",
        "booking_status_history",
        ["booking_id", "created_at"],
    )

    op.create_table(
        "booking_payments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("booking_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("payment_method", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=True),
        sa.Column("provider_reference", sa.String(length=160), nullable=True),
        sa.Column("idempotency_key", sa.String(length=160), nullable=True),
        sa.Column("reference_note", sa.String(length=200), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_by_admin_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_booking_payment_amount_positive"),
        sa.CheckConstraint(
            "payment_method IN ('online', 'cash', 'upi', 'bank_transfer', 'waived')",
            name="ck_booking_payment_method",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'verified', 'failed', 'refund_required', 'waived')",
            name="ck_booking_payment_record_status",
        ),
        sa.ForeignKeyConstraint(
            ["booking_id"], ["bookings.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by_admin_id"], ["admin_accounts.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_reference"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index(
        "ix_booking_payments_booking_created",
        "booking_payments",
        ["booking_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_booking_payments_booking_created", table_name="booking_payments")
    op.drop_table("booking_payments")
    op.drop_index("ix_booking_history_booking_created", table_name="booking_status_history")
    op.drop_table("booking_status_history")
    op.drop_index("ix_bookings_status_created", table_name="bookings")
    op.drop_index("ix_bookings_customer_created", table_name="bookings")
    op.drop_index("ix_bookings_vehicle_status_dates", table_name="bookings")
    op.drop_index("ix_bookings_vehicle_id", table_name="bookings")
    op.drop_index("ix_bookings_customer_id", table_name="bookings")
    op.drop_index("ix_bookings_reference", table_name="bookings")
    op.drop_table("bookings")
