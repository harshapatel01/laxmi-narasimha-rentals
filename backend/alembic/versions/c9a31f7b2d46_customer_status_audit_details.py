"""add details to authentication audit events

Revision ID: c9a31f7b2d46
Revises: 7c4a91d2e8f0
Create Date: 2026-10-28 21:43:39
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9a31f7b2d46"
down_revision: Union[str, Sequence[str], None] = "7c4a91d2e8f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "authentication_audit_logs",
        sa.Column("details", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("authentication_audit_logs", "details")
