from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Optional

import sqlalchemy as sa
from fastapi import HTTPException, status
from sqlmodel import Session, col, select

from src.models import CoinTransaction, User
from src.models.enums import TxType

logger = logging.getLogger("sottovoce.ad_service")

REWARD_PER_AD = 20
REWARD_PER_SHARE = 20
MAX_DAILY_SHARE_REWARDS = 5
COOLDOWN_SECONDS = 10  # Minimo intervallo tra un annuncio e il successivo


async def claim_ad_reward_service(
    session: Session,
    user_id: int,
) -> dict[str, Any]:
    """Credit 20 coins to a user upon completing a rewarded ad view."""
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utente non trovato",
        )

    now = datetime.now(timezone.utc)

    # Cooldown anti-spam
    if user.last_ad_watched_at:
        last_ad = user.last_ad_watched_at
        if last_ad.tzinfo is None:
            last_ad = last_ad.replace(tzinfo=timezone.utc)
        elapsed = (now - last_ad).total_seconds()
        if elapsed < COOLDOWN_SECONDS:
            remaining = int(COOLDOWN_SECONDS - elapsed)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Attendi ancora {remaining}s prima di guardare un altro annuncio",
            )

    try:
        user.coins_balance += REWARD_PER_AD
        user.ads_watched_count += 1
        user.last_ad_watched_at = now

        if user.id is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )
        tx = CoinTransaction(
            user_id=user.id,
            amount=REWARD_PER_AD,
            balance_after=user.coins_balance,
            tx_type=TxType.AD_REWARD,
        )

        session.add(tx)
        session.add(user)
        session.commit()
        session.refresh(user)

        logger.info(
            "User %s rewarded %d coins for watching ad. New balance: %d",
            user.id,
            REWARD_PER_AD,
            user.coins_balance,
        )

        return {
            "status": "success",
            "reward": REWARD_PER_AD,
            "coins_balance": user.coins_balance,
            "ads_watched_count": user.ads_watched_count,
            "message": f"+{REWARD_PER_AD} monete accreditate con successo!",
        }

    except HTTPException:
        session.rollback()
        raise
    except Exception as exc:
        session.rollback()
        logger.error("Failed to credit ad reward to user %s: %s", user_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Errore durante l'accredito della ricompensa: {str(exc)}",
        )


async def claim_share_reward_service(
    session: Session,
    user_id: int,
    confession_id: Optional[int] = None,
) -> dict[str, Any]:
    """Credit +20 coins for sharing Sottovoce or a confession (capped for anti-spam)."""
    user = session.exec(
        select(User).where(User.id == user_id).with_for_update()
    ).one_or_none()
    if not user or user.id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Utente non trovato",
        )

    since_24h = datetime.now(timezone.utc) - timedelta(hours=24)

    # 1. If sharing a specific confession, reward once per confession
    if confession_id is not None:
        already_shared_post = session.exec(
            select(CoinTransaction.id)
            .where(
                CoinTransaction.user_id == user.id,
                CoinTransaction.tx_type == TxType.REFERRAL_BONUS,
                CoinTransaction.target_confession_id == confession_id,
            )
            .limit(1)
        ).first()
        if already_shared_post is not None:
            return {
                "status": "already_claimed",
                "rewarded": False,
                "reward": 0,
                "coins_balance": user.coins_balance,
                "message": "Bonus già riscattato per questo segreto.",
            }
    else:
        # Direct game share: once every 24h
        already_shared_app = session.exec(
            select(CoinTransaction.id)
            .where(
                CoinTransaction.user_id == user.id,
                CoinTransaction.tx_type == TxType.REFERRAL_BONUS,
                col(CoinTransaction.target_confession_id).is_(None),
                CoinTransaction.created_at >= since_24h,
            )
            .limit(1)
        ).first()
        if already_shared_app is not None:
            return {
                "status": "already_claimed",
                "rewarded": False,
                "reward": 0,
                "coins_balance": user.coins_balance,
                "message": "Hai già ricevuto le 20 🪙 di oggi! Riceverai altre +20 🪙 per ogni amico che entra dal tuo link.",
            }

    # 2. Daily anti-spam cap across all shares
    daily_count = session.exec(
        select(sa.func.count())
        .select_from(CoinTransaction)
        .where(
            CoinTransaction.user_id == user.id,
            CoinTransaction.tx_type == TxType.REFERRAL_BONUS,
            CoinTransaction.created_at >= since_24h,
        )
    ).one()
    if int(daily_count or 0) >= MAX_DAILY_SHARE_REWARDS:
        return {
            "status": "daily_limit",
            "rewarded": False,
            "reward": 0,
            "coins_balance": user.coins_balance,
            "message": "Limite giornaliero bonus condivisioni raggiunto! (+20 🪙 extra per ogni amico che entra).",
        }

    user.coins_balance += REWARD_PER_SHARE
    session.add(user)
    session.add(
        CoinTransaction(
            user_id=user.id,
            amount=REWARD_PER_SHARE,
            balance_after=user.coins_balance,
            tx_type=TxType.REFERRAL_BONUS,
            target_confession_id=confession_id,
        )
    )
    session.commit()
    session.refresh(user)

    return {
        "status": "success",
        "rewarded": True,
        "reward": REWARD_PER_SHARE,
        "coins_balance": user.coins_balance,
        "message": f"Hai guadagnato +{REWARD_PER_SHARE} monete per la condivisione! 🪙",
    }
