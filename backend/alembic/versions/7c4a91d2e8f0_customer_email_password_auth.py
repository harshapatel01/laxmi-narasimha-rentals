"""add customer email and password authentication

Revision ID: 7c4a91d2e8f0
Revises: 48f6b6b846a1
Create Date: 2026-10-28 15:30:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7c4a91d2e8f0"
down_revision: Union[str, Sequence[str], None] = "48f6b6b846a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email", sa.String(length=254), nullable=True))
    op.add_column("users", sa.Column("password_hash", sa.String(length=255), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "mobile_verified",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "failed_login_attempts",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column("users", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "customer_password_reset_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("request_ip", sa.String(length=45), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        "ix_customer_password_reset_user_created",
        "customer_password_reset_tokens",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_customer_password_reset_ip_created",
        "customer_password_reset_tokens",
        ["request_ip", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_customer_password_reset_ip_created",
        table_name="customer_password_reset_tokens",
    )
    op.drop_index(
        "ix_customer_password_reset_user_created",
        table_name="customer_password_reset_tokens",
    )
    op.drop_table("customer_password_reset_tokens")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_attempts")
    op.drop_column("users", "mobile_verified")
    op.drop_column("users", "password_hash")
    op.drop_column("users", "email")
