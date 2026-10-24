from datetime import datetime, timedelta, timezone
import logging
from typing import Any

import sqlalchemy as sa
from fastapi import HTTPException, status
from sqlmodel import Session, col, select

from src.models import CoinTransaction, Confession, User
from src.models.enums import ModerationStatus, TxType
from src.services.redis_service import get_cache, invalidate_feed_cache, set_cache

logger = logging.getLogger("sottovoce.leaderboard_service")

PODIUM_REWARDS = {
    1: 200,
    2: 150,
    3: 100,
}

LEADERBOARD_CACHE_TTL_SECONDS = 30


async def _get_weekly_leaderboard(
    session: Session,
    *,
    metric_col: Any,
    cache_prefix: str,
    limit: int,
    days: int,
    include_weekly_rank: bool,
) -> list[dict[str, Any]]:
    """Fetch top confessions in a single query, prioritizing the current week
    and seamlessly filling remaining slots from all-time if < limit exist.
    """
    cache_key = f"sottovoce:leaderboard:{cache_prefix}:{limit}:{days}"
    cached = await get_cache(cache_key)
    if cached is not None:
        return cached

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    recency_bucket = sa.case((col(Confession.created_at) >= cutoff, 0), else_=1)

    query = (
        select(Confession)
        .where(
            Confession.mod_status == ModerationStatus.APPROVED,
            col(Confession.deleted_at).is_(None),
        )
        .order_by(
            recency_bucket.asc(),
            col(metric_col).desc(),
            col(Confession.created_at).desc(),
        )
        .limit(limit)
    )
    confessions = session.exec(query).all()

    results: list[dict[str, Any]] = []
    for index, c in enumerate(confessions):
        rank = index + 1
        total = (
            c.total_reactions
            if c.total_reactions is not None
            else (c.count_skull + c.count_disagio + c.count_popcorn + c.count_clown)
        )
        entry: dict[str, Any] = {
            "rank": rank,
            "reward_coins": PODIUM_REWARDS.get(rank, 0),
            "id": c.id,
            "author_id": c.author_id,
            "content": c.content,
            "ai_roast": c.ai_roast,
            "ai_defense": c.ai_defense,
            "ai_prosecution": c.ai_prosecution,
            "total_reactions": total,
            "shares_count": c.shares_count,
            "count_skull": c.count_skull,
            "count_disagio": c.count_disagio,
            "count_popcorn": c.count_popcorn,
            "count_clown": c.count_clown,
            "created_at": c.created_at,
        }
        if include_weekly_rank:
            entry["weekly_rank"] = c.weekly_rank or (rank if rank <= 3 else None)
        results.append(entry)

    await set_cache(cache_key, results, ttl_seconds=LEADERBOARD_CACHE_TTL_SECONDS)
    return results


async def get_top_secrets_weekly(
    session: Session,
    limit: int = 10,
    days: int = 7,
) -> list[dict[str, Any]]:
    """Retrieve top secrets of the week ordered by total reactions."""
    return await _get_weekly_leaderboard(
        session,
        metric_col=Confession.total_reactions,
        cache_prefix="secrets",
        limit=limit,
        days=days,
        include_weekly_rank=True,
    )


async def get_top_shares_weekly(
    session: Session,
    limit: int = 10,
    days: int = 7,
) -> list[dict[str, Any]]:
    """Retrieve top shared secrets of the week ordered by shares count."""
    return await _get_weekly_leaderboard(
        session,
        metric_col=Confession.shares_count,
        cache_prefix="shares",
        limit=limit,
        days=days,
        include_weekly_rank=False,
    )


async def record_confession_share_service(
    session: Session,
    confession_id: int,
) -> int:
    """Increment the share counter for a confession."""
    confession = session.get(Confession, confession_id)
    if not confession or confession.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Confession not found",
        )

    confession.shares_count += 1
    new_count = confession.shares_count
    session.add(confession)
    session.commit()
    return new_count


def _award_podium_group(
    session: Session,
    items: list[dict[str, Any]],
    *,
    assign_weekly_rank: bool,
) -> list[dict[str, Any]]:
    awards: list[dict[str, Any]] = []
    for item in items[:3]:
        rank = item["rank"]
        reward = PODIUM_REWARDS.get(rank, 0)
        if reward <= 0:
            continue

        confession = session.get(Confession, item["id"])
        if not confession:
            continue

        if assign_weekly_rank:
            confession.weekly_rank = rank
            session.add(confession)

        author = session.get(User, confession.author_id)
        if author and author.id is not None:
            author.coins_balance += reward
            session.add(author)
            session.add(
                CoinTransaction(
                    user_id=author.id,
                    amount=reward,
                    balance_after=author.coins_balance,
                    tx_type=TxType.WEEKLY_PODIUM,
                    target_confession_id=confession.id,
                )
            )

        awards.append(
            {
                "confession_id": confession.id,
                "author_id": confession.author_id,
                "rank": rank,
                "coins_awarded": reward,
            }
        )
    return awards


async def distribute_weekly_podium_rewards(
    session: Session,
) -> dict[str, Any]:
    """Distribute weekly podium coin rewards (200 / 150 / 100) to top 3 reactions & shares."""
    try:
        top_reactions = await get_top_secrets_weekly(session=session, limit=3, days=7)
        reaction_awards = _award_podium_group(
            session, top_reactions, assign_weekly_rank=True
        )

        top_shares = await get_top_shares_weekly(session=session, limit=3, days=7)
        shares_awards = _award_podium_group(
            session, top_shares, assign_weekly_rank=False
        )

        session.commit()
        await invalidate_feed_cache()

        logger.info(
            "Weekly podium rewards distributed: %d reaction awards, %d share awards",
            len(reaction_awards),
            len(shares_awards),
        )
        return {
            "status": "success",
            "reactions_podium": reaction_awards,
            "shares_podium": shares_awards,
        }

    except Exception as exc:
        session.rollback()
        logger.error("Failed to distribute weekly podium rewards: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to distribute weekly rewards: {str(exc)}",
        )
