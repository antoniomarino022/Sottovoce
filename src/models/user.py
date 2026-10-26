from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional
import uuid

import sqlalchemy as sa
from sqlmodel import Column, Field, Relationship, SQLModel

from src.models.enums import UserStatus, pg_enum

if TYPE_CHECKING:
    from src.models.confession import Confession
    from src.models.coin_transaction import CoinTransaction
    from src.models.reaction import Reaction


class User(SQLModel, table=True):
    __tablename__ = "users"
    __table_args__ = (
        sa.CheckConstraint("coins_balance >= 0", name="chk_users_coins_balance"),
        sa.Index(
            "idx_users_referred_by",
            "referred_by_id",
            postgresql_where=sa.text("referred_by_id IS NOT NULL"),
        ),
    )

    id: Optional[int] = Field(
        default=None,
        primary_key=True,
    )
    user_key: str = Field(
        sa_column=Column(sa.CHAR(64), unique=True, nullable=False),
        description="HMAC-SHA256(telegram_id, secret)",
    )
    status: UserStatus = Field(
        default=UserStatus.ACTIVE,
        sa_column=Column(
            pg_enum(UserStatus, "user_status"),
            nullable=False,
            server_default=UserStatus.ACTIVE.value,
        ),
    )
    ban_reason: Optional[str] = Field(
        default=None,
        sa_column=Column(sa.Text, nullable=True),
    )
    banned_until: Optional[datetime] = Field(
        default=None,
        sa_column=Column(sa.DateTime(timezone=True), nullable=True),
    )

    # Portafoglio & Referral
    coins_balance: int = Field(
        default=50,
        sa_column=Column(sa.Integer, nullable=False, server_default="50"),
    )
    referral_code: str = Field(
        sa_column=Column(sa.String(16), unique=True, nullable=False),
    )
    referred_by_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    referral_qualified_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(sa.DateTime(timezone=True), nullable=True),
    )

    # Rate limiting & GDPR
    trust_score: int = Field(
        default=100,
        sa_column=Column(sa.Integer, nullable=False, server_default="100"),
    )
    last_post_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(sa.DateTime(timezone=True), nullable=True),
    )
    last_ad_watched_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(sa.DateTime(timezone=True), nullable=True),
    )
    ads_watched_count: int = Field(
        default=0,
        sa_column=Column(sa.Integer, nullable=False, server_default="0"),
    )
    terms_accepted_at: datetime = Field(
        sa_column=Column(sa.DateTime(timezone=True), nullable=False),
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
    referred_by: Optional["User"] = Relationship(
        back_populates="referrals",
        sa_relationship_kwargs={
            "remote_side": "User.id",
            "foreign_keys": "[User.referred_by_id]",
        },
    )
    referrals: list["User"] = Relationship(
        back_populates="referred_by",
        sa_relationship_kwargs={
            "foreign_keys": "[User.referred_by_id]",
        },
    )
    confessions: list["Confession"] = Relationship(
        back_populates="author",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    reactions: list["Reaction"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    transactions: list["CoinTransaction"] = Relationship(
        back_populates="user",
    )
