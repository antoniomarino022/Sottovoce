"""002_optimize_navigation_indexes

Revision ID: 002_optimize_navigation_indexes
Revises: 001_initial_schema
Create Date: 2026-10-24 19:30:00.000000

Align composite index column order with popular feed & leaderboard ORDER BY clauses,
drop duplicate single-column reaction index, and add covering user-reactions index.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "002_optimize_navigation_indexes"
down_revision: Union[str, None] = "001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Fix column order so ORDER BY total_reactions DESC / shares_count DESC uses B-tree order directly
    op.execute("DROP INDEX IF EXISTS idx_leaderboard;")
    op.execute(
        "CREATE INDEX idx_leaderboard ON confessions (total_reactions DESC, created_at DESC) "
        "WHERE mod_status = 'approved' AND deleted_at IS NULL;"
    )

    op.execute("DROP INDEX IF EXISTS idx_shares_leaderboard;")
    op.execute(
        "CREATE INDEX idx_shares_leaderboard ON confessions (shares_count DESC, created_at DESC) "
        "WHERE mod_status = 'approved' AND deleted_at IS NULL;"
    )

    # 2. Drop duplicate index (already covered by uq_reactions_confession_user leftmost prefix)
    op.execute("DROP INDEX IF EXISTS idx_reactions_confession;")

    # 3. Add covering index for per-user feed reaction personalization (Index-Only Scan)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_reactions_user_confession "
        "ON reactions (user_id, confession_id) INCLUDE (type);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_reactions_user_confession;")
    op.execute("CREATE INDEX IF NOT EXISTS idx_reactions_confession ON reactions (confession_id);")

    op.execute("DROP INDEX IF EXISTS idx_leaderboard;")
    op.execute(
        "CREATE INDEX idx_leaderboard ON confessions (created_at DESC, total_reactions DESC) "
        "WHERE mod_status = 'approved' AND deleted_at IS NULL;"
    )

    op.execute("DROP INDEX IF EXISTS idx_shares_leaderboard;")
    op.execute(
        "CREATE INDEX idx_shares_leaderboard ON confessions (created_at DESC, shares_count DESC) "
        "WHERE mod_status = 'approved' AND deleted_at IS NULL;"
    )
