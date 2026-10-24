from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from fastapi import HTTPException, status
from sqlmodel import Session

from src.models import CoinTransaction, User
from src.models.enums import TxType

logger = logging.getLogger("hotmic.ad_service")

REWARD_PER_AD = 20
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

    except Exception as exc:
        session.rollback()
        logger.error("Failed to credit ad reward to user %s: %s", user_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Errore durante l'accredito della ricompensa: {str(exc)}",
        )
