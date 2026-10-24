from datetime import datetime, timezone
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from config.database import get_session
from src.models import User
from src.routers.deps import get_current_user
from src.services.ad_service import COOLDOWN_SECONDS, claim_ad_reward_service

logger = logging.getLogger("hotmic.ad_router")

router = APIRouter(prefix="/ads", tags=["Ads & Monetization"])


@router.post("/reward", status_code=status.HTTP_200_OK)
async def claim_ad_reward(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Claim +20 coins reward for completing an Adsgram rewarded video."""
    if current_user.id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticazione richiesta",
        )

    result = await claim_ad_reward_service(
        session=session,
        user_id=current_user.id,
    )
    return result


@router.get("/status", status_code=status.HTTP_200_OK)
async def get_ad_status(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Check if the user is eligible to watch an ad or currently on cooldown."""
    can_watch = True
    cooldown_remaining = 0

    if current_user.last_ad_watched_at:
        now = datetime.now(timezone.utc)
        last_ad = current_user.last_ad_watched_at
        if last_ad.tzinfo is None:
            last_ad = last_ad.replace(tzinfo=timezone.utc)
        elapsed = (now - last_ad).total_seconds()
        if elapsed < COOLDOWN_SECONDS:
            can_watch = False
            cooldown_remaining = int(COOLDOWN_SECONDS - elapsed)

    return {
        "can_watch": can_watch,
        "cooldown_remaining": cooldown_remaining,
        "coins_balance": current_user.coins_balance,
        "ads_watched_count": current_user.ads_watched_count,
    }
