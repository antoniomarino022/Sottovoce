import logging
from contextlib import contextmanager
from typing import Any, Awaitable, Callable, Literal, NamedTuple, Optional

import sqlalchemy as sa
from fastapi import HTTPException, status
from sqlmodel import Session, col, select

from src.agents import (
    run_confession_pipeline,
    run_defense_agent,
    run_prosecution_agent,
)
from src.models import CoinTransaction, Confession, Reaction, User
from src.models.enums import ModerationStatus, TxType
from src.schemas import ConfessionCreate
from src.services.redis_service import (
    get_cache,
    get_feed_version,
    invalidate_feed_cache,
    set_cache,
)

logger = logging.getLogger(__name__)

COST_DEFENSE = 20
COST_PROSECUTION = 20
FEED_CACHE_TTL_SECONDS = 20

FeedType = Literal["latest", "popular", "my"]


class _AgentInput(NamedTuple):
    """Plain-value snapshot extracted before commit so LLM calls hold zero DB state."""

    confession_id: int
    content: str
    ai_roast: str
    ai_defense: Optional[str]


def _not_found(what: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found")


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail)


def _insufficient_coins(cost: int) -> HTTPException:
    return _bad_request(f"Saldo monete insufficiente (richieste {cost} monete)")


def _refresh_if_expired(session: Session, obj: Any) -> None:
    """Refresh ORM instance only if session has expire_on_commit=True (e.g. unit tests)."""
    state = sa.inspect(obj, raiseerr=False)
    if state is not None and state.expired:
        session.refresh(obj)


@contextmanager
def db_errors(session: Session, action: str):
    """Roll back the session on any error, re-raising HTTPExceptions unchanged."""
    try:
        yield
    except HTTPException:
        session.rollback()
        raise
    except Exception:
        session.rollback()
        logger.exception("Failed to %s", action)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to {action}",
        )


def _get_active_confession(session: Session, confession_id: int) -> Confession:
    """Return the confession only if it exists and is not soft-deleted."""
    confession = session.get(Confession, confession_id)
    if confession is None or confession.deleted_at is not None or confession.id is None:
        raise _not_found("Confession")
    return confession


def _ensure_can_afford(session: Session, user_id: int, cost: int) -> None:
    """Fast balance check without row locks to fail early before calling the LLM."""
    user = session.get(User, user_id)
    if user is None or user.id is None:
        raise _not_found("User")
    if user.coins_balance < cost:
        raise _insufficient_coins(cost)


def _charge_user(
    session: Session,
    user_id: int,
    cost: int,
    tx_type: TxType,
    confession_id: int,
) -> None:
    """Deduct coins under a row lock (SELECT ... FOR UPDATE) inside the save transaction."""
    user = session.exec(
        select(User).where(User.id == user_id).with_for_update()
    ).one_or_none()
    if user is None or user.id is None:
        raise _not_found("User")
    if user.coins_balance < cost:
        raise _insufficient_coins(cost)

    user.coins_balance -= cost
    session.add(user)
    session.add(
        CoinTransaction(
            user_id=user.id,
            amount=-cost,
            balance_after=user.coins_balance,
            tx_type=tx_type,
            target_confession_id=confession_id,
        )
    )


def get_user_reactions_map(
    session: Session,
    user_id: int,
    confession_ids: list[int],
) -> dict[int, Any]:
    """Fetch only (confession_id, type) scalars for the given confessions."""
    if not confession_ids:
        return {}
    rows = session.exec(
        select(Reaction.confession_id, Reaction.type).where(
            Reaction.user_id == user_id,
            col(Reaction.confession_id).in_(confession_ids),
        )
    ).all()
    return {cid: r_type for cid, r_type in rows}


# Backward-compatible internal alias
_get_user_reactions = get_user_reactions_map


def _is_author(author_id: Optional[int], current_user_id: Optional[int]) -> bool:
    return current_user_id is not None and author_id == current_user_id


def serialize_confession(
    confession: Confession,
    user_reaction: Any = None,
    current_user_id: Optional[int] = None,
) -> dict[str, Any]:
    """Convert a confession ORM object to a template/API dict."""
    total = confession.total_reactions
    if total is None:
        total = (
            confession.count_skull
            + confession.count_disagio
            + confession.count_popcorn
            + confession.count_clown
        )

    return {
        **confession.model_dump(),
        "total_reactions": total,
        "user_reaction": user_reaction,
        "is_author": _is_author(confession.author_id, current_user_id),
    }


_serialize = serialize_confession


# --------------------------------------------------------------------------- #
# Create / delete
# --------------------------------------------------------------------------- #
async def create_confession_service(
    session: Session,
    author_id: int,
    data: ConfessionCreate,
) -> Confession:
    """Persist a new confession and run Triage + Judge without holding DB locks during LLM."""
    with db_errors(session, "persist confession"):
        confession = Confession(
            **data.model_dump(exclude={"author_id"}),
            author_id=author_id,
        )
        session.add(confession)
        content_text = confession.content
        session.commit()
        _refresh_if_expired(session, confession)

        if confession.id is not None:
            cid = confession.id
            # Release any open transaction before the 2-6s external LLM call
            session.commit()
            result = await run_confession_pipeline(
                content=content_text,
                confession_id=cid,
            )
            confession = _get_active_confession(session, cid)
            confession.mod_status = ModerationStatus(result.get("mod_status", "crisis_held"))
            confession.severity = int(result.get("severity", 0))
            confession.ai_roast = result.get("ai_roast")
            session.add(confession)
            session.commit()
            _refresh_if_expired(session, confession)

        await invalidate_feed_cache()
        return confession


async def delete_confession_service(
    session: Session,
    author_id: int,
    id: int,
) -> dict:
    """Permanently delete a confession after checking existence and ownership."""
    with db_errors(session, "delete confession"):
        confession = session.get(Confession, id)
        if confession is None:
            raise _not_found("Confession")
        if confession.author_id != author_id:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "You are not authorized to delete this confession",
            )

        session.delete(confession)
        session.commit()
        await invalidate_feed_cache()
        return {"status": "ok", "message": "Confession deleted successfully"}


# --------------------------------------------------------------------------- #
# AI pipeline & courtroom powers
# --------------------------------------------------------------------------- #
async def process_confession_ai_pipeline(
    session: Session,
    confession_id: int,
) -> Confession:
    """Run Triage + Judge on an existing confession without holding DB locks during LLM."""
    with db_errors(session, "process confession AI pipeline"):
        confession = session.get(Confession, confession_id)
        if confession is None or confession.id is None:
            raise _not_found("Confession for AI processing")

        content_text = confession.content
        cid = confession.id
        session.commit()

        result = await run_confession_pipeline(
            content=content_text,
            confession_id=cid,
        )

        confession = _get_active_confession(session, cid)
        confession.mod_status = ModerationStatus(result.get("mod_status", "crisis_held"))
        confession.severity = int(result.get("severity", 0))
        confession.ai_roast = result.get("ai_roast")

        session.add(confession)
        session.commit()
        _refresh_if_expired(session, confession)
        return confession


def _validate_confession_for_agent(confession: Confession, label: str) -> None:
    name = label.capitalize()
    if confession.mod_status != ModerationStatus.APPROVED:
        raise _bad_request(f"{name} can only be invoked for approved confessions")
    if not confession.ai_roast:
        raise _bad_request(f"{name} requires a prior judge roast")


async def _invoke_agent(
    session: Session,
    confession_id: int,
    user_id: Optional[int] = None,
    *,
    label: str,
    cost: int,
    tx_type: TxType,
    field: str,
    runner: Callable[[_AgentInput], Awaitable[dict]],
) -> Confession:
    """Validate, release DB transaction, run LLM, then atomically charge + save."""
    with db_errors(session, f"invoke {label} agent"):
        confession = _get_active_confession(session, confession_id)
        _validate_confession_for_agent(confession, label)
        if user_id is not None:
            _ensure_can_afford(session, user_id, cost)

        # Snapshot primitives BEFORE commit so no lazy SELECT re-opens a transaction
        snapshot = _AgentInput(
            confession_id=confession_id,
            content=confession.content,
            ai_roast=confession.ai_roast or "",
            ai_defense=confession.ai_defense,
        )
        session.commit()

        result = await runner(snapshot)

        confession = _get_active_confession(session, confession_id)
        if user_id is not None:
            _charge_user(session, user_id, cost, tx_type, confession_id)

        setattr(confession, field, result.get(field))
        session.add(confession)
        session.commit()
        _refresh_if_expired(session, confession)

        await invalidate_feed_cache()
        return confession


async def invoke_defense_service(
    session: Session,
    confession_id: int,
    user_id: Optional[int] = None,
) -> Confession:
    return await _invoke_agent(
        session,
        confession_id,
        user_id,
        label="defense",
        cost=COST_DEFENSE,
        tx_type=TxType.BUY_AI_LAWYER,
        field="ai_defense",
        runner=lambda inp: run_defense_agent(
            confession_id=inp.confession_id,
            content=inp.content,
            ai_roast=inp.ai_roast,
        ),
    )


async def invoke_prosecution_service(
    session: Session,
    confession_id: int,
    user_id: Optional[int] = None,
) -> Confession:
    return await _invoke_agent(
        session,
        confession_id,
        user_id,
        label="prosecution",
        cost=COST_PROSECUTION,
        tx_type=TxType.BUY_AI_PROSECUTOR,
        field="ai_prosecution",
        runner=lambda inp: run_prosecution_agent(
            confession_id=inp.confession_id,
            content=inp.content,
            ai_roast=inp.ai_roast,
            ai_defense=inp.ai_defense,
        ),
    )


# --------------------------------------------------------------------------- #
# Read: single confession & feeds
# --------------------------------------------------------------------------- #
async def get_confession_by_id_service(
    session: Session,
    confession_id: int,
    current_user_id: Optional[int] = None,
) -> dict[str, Any]:
    """Single confession with total reactions and the current user's reaction."""
    confession = _get_active_confession(session, confession_id)

    user_reaction = None
    if current_user_id is not None:
        reactions = get_user_reactions_map(session, current_user_id, [confession_id])
        user_reaction = reactions.get(confession_id)

    return serialize_confession(confession, user_reaction, current_user_id)


async def _feed_cache_key(
    feed_type: FeedType,
    limit: int,
    offset: int,
    current_user_id: Optional[int],
) -> str:
    ver = await get_feed_version()
    if feed_type == "my":
        if current_user_id is None:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "Authentication required to view personal confessions",
            )
        return f"hotmic:feed:v{ver}:my:{current_user_id}:{limit}:{offset}"
    return f"hotmic:feed:v{ver}:{feed_type}:{limit}:{offset}"


def _build_feed_query(feed_type: FeedType, current_user_id: Optional[int]):
    query = select(Confession).where(col(Confession.deleted_at).is_(None))

    if feed_type == "my":
        return query.where(Confession.author_id == current_user_id).order_by(
            col(Confession.created_at).desc()
        )

    query = query.where(Confession.mod_status == ModerationStatus.APPROVED)

    if feed_type == "popular":
        return query.order_by(
            col(Confession.total_reactions).desc(),
            col(Confession.created_at).desc(),
        )

    return query.order_by(
        col(Confession.pinned_until).desc().nullslast(),
        col(Confession.created_at).desc(),
    )


async def _load_feed_items(
    session: Session,
    feed_type: FeedType,
    limit: int,
    offset: int,
    current_user_id: Optional[int],
) -> list[dict[str, Any]]:
    cache_key = await _feed_cache_key(feed_type, limit, offset, current_user_id)

    items = await get_cache(cache_key)
    if items is not None:
        return items

    query = _build_feed_query(feed_type, current_user_id)
    confessions = session.exec(query.offset(offset).limit(limit)).all()
    items = [serialize_confession(c) for c in confessions]
    await set_cache(cache_key, items, ttl_seconds=FEED_CACHE_TTL_SECONDS)
    return items


async def get_feed_confessions_service(
    session: Session,
    feed_type: FeedType = "latest",
    limit: int = 20,
    offset: int = 0,
    current_user_id: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Feed with aggregate reaction totals and the user's own reactions, cached via Redis."""
    with db_errors(session, "fetch feed"):
        items = await _load_feed_items(
            session, feed_type, limit, offset, current_user_id
        )

        reactions_by_confession: dict[int, Any] = {}
        if current_user_id is not None and items:
            ids = [item["id"] for item in items if item.get("id") is not None]
            reactions_by_confession = get_user_reactions_map(session, current_user_id, ids)

        return [
            {
                **item,
                "user_reaction": reactions_by_confession.get(item["id"]),
                "is_author": _is_author(item.get("author_id"), current_user_id),
            }
            for item in items
        ]
