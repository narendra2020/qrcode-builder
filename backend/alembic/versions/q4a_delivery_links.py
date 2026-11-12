"""QR Store Builder: Zomato / Swiggy links on stores

Revision ID: q4d3f6b8c0e2
Revises: q3c2e5a7b9d1
Create Date: 2026-11-10
"""
from alembic import op
import sqlalchemy as sa

revision = "q4d3f6b8c0e2"
down_revision = "q3c2e5a7b9d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("qr_stores", sa.Column("zomato_url", sa.String(500), nullable=True))
    op.add_column("qr_stores", sa.Column("swiggy_url", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("qr_stores", "swiggy_url")
    op.drop_column("qr_stores", "zomato_url")
