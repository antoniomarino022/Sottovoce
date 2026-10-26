"""003_add_telegram_id_to_users

Revision ID: 003_add_telegram_id_to_users
Revises: 002_optimize_navigation_indexes
Create Date: 2026-10-26 21:30:00.000000

Add telegram_id column and index to users table for Bot notifications.
"""
from typing import Sequence, Union
from alembic import op

revision: str = "003_add_telegram_id_to_users"
down_revision: Union[str, None] = "002_optimize_navigation_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_id BIGINT UNIQUE;")
    op.execute("CREATE INDEX IF NOT EXISTS ix_users_telegram_id ON users (telegram_id);")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_users_telegram_id;")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS telegram_id;")
