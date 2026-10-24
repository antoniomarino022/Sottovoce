from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional
import uuid

import sqlalchemy as sa
from sqlmodel import Column, Field, Relationship, SQLModel

from src.models.enums import ReactionType, pg_enum

if TYPE_CHECKING:
    from src.models.confession import Confession
    from src.models.user import User


class Reaction(SQLModel, table=True):
    __tablename__ = "reactions"
    __table_args__ = (
        sa.UniqueConstraint("confession_id", "user_id", name="uq_reactions_confession_user"),
        sa.Index("idx_reactions_user_confession", "user_id", "confession_id"),
    )

    id: Optional[int] = Field(
        default=None,
        primary_key=True,
    )
    confession_id: int = Field(
        sa_column=Column(
            sa.Integer,
            sa.ForeignKey("confessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    user_id: int = Field(
        sa_column=Column(
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    type: ReactionType = Field(
        sa_column=Column(
            pg_enum(ReactionType, "reaction_type"),
            nullable=False,
        ),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Relationships
    confession: Optional["Confession"] = Relationship(
        back_populates="reactions",
    )
    user: Optional["User"] = Relationship(
        back_populates="reactions",
    )
