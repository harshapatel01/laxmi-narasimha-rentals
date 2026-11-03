"""add persistent booking notifications and payment notes

Revision ID: e4b9c31a7d20
Revises: c9a31f7b2d46
Create Date: 2026-10-29 00:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e4b9c31a7d20"
down_revision: Union[str, Sequence[str], None] = "c9a31f7b2d46"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("booking_payments", sa.Column("notes", sa.Text(), nullable=True))
    op.create_table(
        "booking_notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_event_id", sa.Uuid(), nullable=False),
        sa.Column("booking_id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("email_status", sa.String(length=24), nullable=False),
        sa.Column(
            "email_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("email_error", sa.Text(), nullable=True),
        sa.Column("email_last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("email_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_event_id"], ["booking_status_history.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_event_id"),
    )
    op.create_index(
        "ix_booking_notifications_customer_created",
        "booking_notifications",
        ["customer_id", "created_at"],
    )
    op.create_index(
        "ix_booking_notifications_email_status",
        "booking_notifications",
        ["email_status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_booking_notifications_email_status", table_name="booking_notifications")
    op.drop_index("ix_booking_notifications_customer_created", table_name="booking_notifications")
    op.drop_table("booking_notifications")
    op.drop_column("booking_payments", "notes")
