from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
from sqlmodel import Column, Field, Relationship, SQLModel

from src.models.enums import TxType, pg_enum

if TYPE_CHECKING:
    from src.models.confession import Confession
    from src.models.user import User


class CoinTransaction(SQLModel, table=True):
    __tablename__ = "coin_transactions"
    __table_args__ = (
        sa.CheckConstraint("amount <> 0", name="chk_coin_tx_amount"),
        sa.CheckConstraint("balance_after >= 0", name="chk_coin_tx_balance_after"),
        sa.CheckConstraint("stars_paid > 0", name="chk_coin_tx_stars_paid"),
        sa.Index(
            "idx_wallet_history",
            "user_id",
            sa.text("created_at DESC"),
        ),
        sa.Index(
            "idx_tx_target_confession",
            "target_confession_id",
            postgresql_where=sa.text("target_confession_id IS NOT NULL"),
        ),
    )

    id: Optional[int] = Field(
        default=None,
        primary_key=True,
    )
    user_id: int = Field(
        sa_column=Column(
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
    )
    amount: int = Field(
        sa_column=Column(sa.Integer, nullable=False),
    )
    balance_after: int = Field(
        sa_column=Column(sa.Integer, nullable=False),
    )
    tx_type: TxType = Field(
        sa_column=Column(
            pg_enum(TxType, "tx_type"),
            nullable=False,
        ),
    )

    # Campi Telegram Stars
    stars_paid: Optional[int] = Field(
        default=None,
        sa_column=Column(sa.Integer, nullable=True),
    )
    telegram_charge_id: Optional[str] = Field(
        default=None,
        sa_column=Column(sa.String(255), unique=True, nullable=True),
    )

    # Post collegato (se applicabile)
    target_confession_id: Optional[int] = Field(
        default=None,
        sa_column=Column(
            sa.Integer,
            sa.ForeignKey("confessions.id", ondelete="SET NULL"),
            nullable=True,
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
    user: Optional["User"] = Relationship(
        back_populates="transactions",
    )
    target_confession: Optional["Confession"] = Relationship(
        back_populates="transactions",
    )
