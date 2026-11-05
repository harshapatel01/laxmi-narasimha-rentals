"""track independent booking email recipients

Revision ID: f1a2b3c4d5e6
Revises: e4b9c31a7d20
Create Date: 2026-10-29 00:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "e4b9c31a7d20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "booking_email_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_event_id", sa.Uuid(), nullable=False),
        sa.Column("booking_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_type", sa.String(length=16), nullable=False),
        sa.Column("recipient_email", sa.String(length=254), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "recipient_type IN ('customer', 'admin')",
            name="ck_booking_email_job_recipient_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sending', 'accepted_by_provider', "
            "'delivery_unknown', 'failed', 'not_configured')",
            name="ck_booking_email_job_status",
        ),
        sa.ForeignKeyConstraint(
            ["source_event_id"], ["booking_status_history.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_event_id", "recipient_type", name="uq_booking_email_job_event_recipient"
        ),
    )
    op.create_index(
        "ix_booking_email_job_status_created",
        "booking_email_jobs",
        ["status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_booking_email_job_status_created", table_name="booking_email_jobs")
    op.drop_table("booking_email_jobs")
