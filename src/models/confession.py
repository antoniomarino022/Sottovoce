from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional
import uuid

import sqlalchemy as sa
from sqlmodel import Column, Field, Relationship, SQLModel

from src.models.enums import (
    ModerationStatus,
    PostStyle,
    ShameBadge,
    pg_enum,
)

if TYPE_CHECKING:
    from src.models.coin_transaction import CoinTransaction
    from src.models.reaction import Reaction
    from src.models.user import User


class Confession(SQLModel, table=True):
    __tablename__ = "confessions"
    __table_args__ = (
        sa.CheckConstraint(
            "weekly_rank IN (1, 2, 3)",
            name="chk_confessions_weekly_rank",
        ),
        sa.CheckConstraint("count_skull >= 0", name="chk_confessions_count_skull"),
        sa.CheckConstraint("count_disagio >= 0", name="chk_confessions_count_disagio"),
        sa.CheckConstraint("count_popcorn >= 0", name="chk_confessions_count_popcorn"),
        sa.CheckConstraint("count_clown >= 0", name="chk_confessions_count_clown"),
        sa.CheckConstraint("shares_count >= 0", name="chk_confessions_shares_count"),
        sa.Index(
            "idx_public_feed",
            sa.text("pinned_until DESC"),
            sa.text("created_at DESC"),
            postgresql_where=sa.text("mod_status = 'approved' AND deleted_at IS NULL"),
        ),
        sa.Index(
            "idx_leaderboard",
            sa.text("total_reactions DESC"),
            sa.text("created_at DESC"),
            postgresql_where=sa.text("mod_status = 'approved' AND deleted_at IS NULL"),
        ),
        sa.Index(
            "idx_shares_leaderboard",
            sa.text("shares_count DESC"),
            sa.text("created_at DESC"),
            postgresql_where=sa.text("mod_status = 'approved' AND deleted_at IS NULL"),
        ),
        sa.Index(
            "idx_confessions_author",
            "author_id",
            sa.text("created_at DESC"),
        ),
    )

    id: Optional[int] = Field(
        default=None,
        primary_key=True,
    )
    author_id: int = Field(
        sa_column=Column(
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    content: str = Field(
        sa_column=Column(sa.Text, nullable=False),
    )

    # Moderazione & Giudice IA Base
    ai_roast: Optional[str] = Field(
        default=None,
        sa_column=Column(sa.Text, nullable=True),
    )
    mod_status: ModerationStatus = Field(
        default=ModerationStatus.PENDING_AI,
        sa_column=Column(
            pg_enum(ModerationStatus, "moderation_status"),
            nullable=False,
            server_default=ModerationStatus.PENDING_AI.value,
        ),
    )
    severity: int = Field(
        default=0,
        sa_column=Column(sa.SmallInteger, nullable=False, server_default="0"),
    )

    # Poteri IA, Sabotaggio & Podio
    ai_defense: Optional[str] = Field(
        default=None,
        sa_column=Column(sa.Text, nullable=True),
    )
    ai_prosecution: Optional[str] = Field(
        default=None,
        sa_column=Column(sa.Text, nullable=True),
    )
    visual_style: PostStyle = Field(
        default=PostStyle.STANDARD,
        sa_column=Column(
            pg_enum(PostStyle, "post_style"),
            nullable=False,
            server_default=PostStyle.STANDARD.value,
        ),
    )
    shame_stamp: ShameBadge = Field(
        default=ShameBadge.NONE,
        sa_column=Column(
            pg_enum(ShameBadge, "shame_badge"),
            nullable=False,
            server_default=ShameBadge.NONE.value,
        ),
    )
    pinned_until: Optional[datetime] = Field(
        default=None,
        sa_column=Column(sa.DateTime(timezone=True), nullable=True),
    )
    weekly_rank: Optional[int] = Field(
        default=None,
        sa_column=Column(sa.SmallInteger, nullable=True),
    )

    # Contatori Reazioni & Segnalazioni
    count_skull: int = Field(
        default=0,
        sa_column=Column(sa.Integer, nullable=False, server_default="0"),
    )
    count_disagio: int = Field(
        default=0,
        sa_column=Column(sa.Integer, nullable=False, server_default="0"),
    )
    count_popcorn: int = Field(
        default=0,
        sa_column=Column(sa.Integer, nullable=False, server_default="0"),
    )
    count_clown: int = Field(
        default=0,
        sa_column=Column(sa.Integer, nullable=False, server_default="0"),
    )

    # Somma automatica gestita da PostgreSQL (zero bug di sincronizzazione)
    total_reactions: Optional[int] = Field(
        default=None,
        sa_column=Column(
            sa.Integer,
            sa.Computed(
                "count_skull + count_disagio + count_popcorn + count_clown",
                persisted=True,
            ),
            nullable=False,
        ),
    )

    shares_count: int = Field(
        default=0,
        sa_column=Column(sa.Integer, nullable=False, server_default="0"),
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    deleted_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(sa.DateTime(timezone=True), nullable=True),
    )

    # Relationships
    author: Optional["User"] = Relationship(
        back_populates="confessions",
    )
    reactions: list["Reaction"] = Relationship(
        back_populates="confession",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    transactions: list["CoinTransaction"] = Relationship(
        back_populates="target_confession",
    )
