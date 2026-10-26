from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlmodel import Session

from config.database import get_session
from config.settings import settings
from src.models import User
from src.routers.deps import get_optional_current_user
from src.services.ad_service import claim_share_reward_service
from src.services.leaderboard_service import (
    distribute_weekly_podium_rewards,
    get_top_secrets_weekly,
    record_confession_share_service,
)

router = APIRouter(tags=["Leaderboard"])


@router.get("/api/leaderboard", status_code=status.HTTP_200_OK)
async def api_leaderboard(
    session: Session = Depends(get_session),
):
    """JSON API to fetch weekly leaderboard rankings."""
    return {
        "secrets": await get_top_secrets_weekly(session=session, limit=10, days=7)
    }


@router.post("/confessions/{confession_id}/share", status_code=status.HTTP_200_OK)
async def share_confession(
    confession_id: int,
    current_user: Optional[User] = Depends(get_optional_current_user),
    session: Session = Depends(get_session),
):
    """Increment the share count for a confession and award +20 coins to the sharer."""
    shares_count = await record_confession_share_service(
        session=session,
        confession_id=confession_id,
    )
    payload = {
        "status": "success",
        "confession_id": confession_id,
        "shares_count": shares_count,
        "rewarded": False,
    }
    if current_user and current_user.id is not None:
        reward_info = await claim_share_reward_service(
            session=session,
            user_id=current_user.id,
            confession_id=confession_id,
        )
        payload["rewarded"] = reward_info["rewarded"]
        payload["reward"] = reward_info["reward"]
        payload["coins_balance"] = reward_info["coins_balance"]
        payload["message"] = reward_info["message"]
    return payload


@router.post("/api/leaderboard/award", status_code=status.HTTP_200_OK)
@router.get("/api/cron/weekly-podium", status_code=status.HTTP_200_OK)
async def award_weekly_podium(
    authorization: Optional[str] = Header(None),
    session: Session = Depends(get_session),
):
    """Distribute weekly podium coin rewards (200, 150, 100 coins) to top 3.
    Can be invoked by external cron services or Vercel Cron.
    """
    cron_secret = settings.CRON_SECRET.get_secret_value().strip()
    if cron_secret:
        auth_value = (authorization or "").replace("Bearer ", "").strip()
        if auth_value != cron_secret:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing Cron Authorization header",
            )

    return await distribute_weekly_podium_rewards(session=session)
