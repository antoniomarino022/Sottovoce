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
from src.models.enums import ModerationStatus, ShameBadge, TxType
from src.schemas import ConfessionCreate
from src.services.notification_service import notify_confession_author
from src.services.redis_service import (
    get_cache,
    get_feed_version,
    invalidate_feed_cache,
    set_cache,
)

logger = logging.getLogger(__name__)

COST_DEFENSE = 20
COST_PROSECUTION = 20
COST_ESCALATE = 10
ESCALATION_AI_THRESHOLDS = frozenset({1, 5, 10})
FEED_CACHE_TTL_SECONDS = 20

FeedType = Literal["latest", "popular", "my"]


class _AgentInput(NamedTuple):
    """Plain-value snapshot extracted before commit so LLM calls hold zero DB state."""

    confession_id: int
    content: str
    ai_roast: str
    ai_defense: Optional[str]
    escalation_count: int


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


_get_user_reactions = get_user_reactions_map


def get_court_counts_map(
    session: Session,
    confession_ids: list[int],
) -> dict[int, tuple[int, int]]:
    """Batch-fetch (defense_count, prosecution_count) per confession in 1 SQL GROUP BY."""
    if not confession_ids:
        return {}
    rows = session.exec(
        select(
            CoinTransaction.target_confession_id,
            CoinTransaction.tx_type,
            sa.func.count(),
        )
        .where(
            col(CoinTransaction.target_confession_id).in_(confession_ids),
            col(CoinTransaction.tx_type).in_(
                [TxType.BUY_AI_LAWYER, TxType.BUY_AI_PROSECUTOR]
            ),
        )
        .group_by(CoinTransaction.target_confession_id, CoinTransaction.tx_type)
    ).all()

    counts: dict[int, list[int]] = {}
    for cid, tx_type, cnt in rows:
        if cid is None:
            continue
        pair = counts.setdefault(cid, [0, 0])
        if tx_type == TxType.BUY_AI_LAWYER:
            pair[0] = int(cnt)
        elif tx_type == TxType.BUY_AI_PROSECUTOR:
            pair[1] = int(cnt)
    return {cid: (pair[0], pair[1]) for cid, pair in counts.items()}


def get_user_court_votes_map(
    session: Session,
    user_id: int,
    confession_ids: list[int],
) -> dict[int, tuple[bool, bool]]:
    """Batch-fetch (user_defended, user_prosecuted) for the current user."""
    if not confession_ids:
        return {}
    rows = session.exec(
        select(CoinTransaction.target_confession_id, CoinTransaction.tx_type).where(
            CoinTransaction.user_id == user_id,
            col(CoinTransaction.target_confession_id).in_(confession_ids),
            col(CoinTransaction.tx_type).in_(
                [TxType.BUY_AI_LAWYER, TxType.BUY_AI_PROSECUTOR]
            ),
        )
    ).all()

    votes: dict[int, list[bool]] = {}
    for cid, tx_type in rows:
        if cid is None:
            continue
        pair = votes.setdefault(cid, [False, False])
        if tx_type == TxType.BUY_AI_LAWYER:
            pair[0] = True
        elif tx_type == TxType.BUY_AI_PROSECUTOR:
            pair[1] = True
    return {cid: (pair[0], pair[1]) for cid, pair in votes.items()}


def _has_user_voted_side(
    session: Session,
    user_id: int,
    confession_id: int,
    tx_type: TxType,
) -> bool:
    existing = session.exec(
        select(CoinTransaction.id)
        .where(
            CoinTransaction.user_id == user_id,
            CoinTransaction.target_confession_id == confession_id,
            CoinTransaction.tx_type == tx_type,
        )
        .limit(1)
    ).first()
    return existing is not None


def _apply_court_badge(
    confession: Confession,
    defense_count: int,
    prosecution_count: int,
) -> None:
    """Update shame_stamp automatically as prosecution/defense escalates."""
    if prosecution_count >= 5 and prosecution_count > defense_count:
        confession.shame_stamp = ShameBadge.CERTIFIED_CLOWN
    elif prosecution_count >= 3 and prosecution_count > defense_count:
        confession.shame_stamp = ShameBadge.WALKING_RED_FLAG
    elif defense_count >= 5 and defense_count >= prosecution_count:
        confession.shame_stamp = ShameBadge.NONE


def _is_author(author_id: Optional[int], current_user_id: Optional[int]) -> bool:
    return current_user_id is not None and author_id == current_user_id


def serialize_confession(
    confession: Confession,
    user_reaction: Any = None,
    current_user_id: Optional[int] = None,
    court_counts: Optional[tuple[int, int]] = None,
    user_votes: Optional[tuple[bool, bool]] = None,
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

    raw_def, raw_pros = court_counts or (0, 0)
    def_count = max(raw_def, 1 if confession.ai_defense else 0)
    pros_count = max(raw_pros, 1 if confession.ai_prosecution else 0)
    u_def, u_pros = user_votes or (False, False)

    return {
        **confession.model_dump(),
        "total_reactions": total,
        "user_reaction": user_reaction,
        "is_author": _is_author(confession.author_id, current_user_id),
        "defense_count": def_count,
        "prosecution_count": pros_count,
        "user_defended": u_def,
        "user_prosecuted": u_pros,
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
            session.commit()
            try:
                result = await run_confession_pipeline(
                    content=content_text,
                    confession_id=cid,
                )
            except Exception as exc:
                logger.exception("Unexpected error in confession pipeline for id=%s: %s", cid, exc)
                result = {"mod_status": "crisis_held", "severity": 10, "ai_roast": None}

            confession = _get_active_confession(session, cid)
            confession.mod_status = ModerationStatus(result.get("mod_status", "crisis_held"))
            confession.severity = int(result.get("severity", 0))
            confession.ai_roast = result.get("ai_roast")
            session.add(confession)
            session.commit()
            _refresh_if_expired(session, confession)

            # Notifica autore sul verdetto della Corte (resiliente ad eventuali blocchi del bot)
            if confession.ai_roast and confession.mod_status == ModerationStatus.APPROVED:
                try:
                    snippet = confession.content[:60] + "..." if len(confession.content) > 60 else confession.content
                    await notify_confession_author(
                        session=session,
                        confession_id=cid,
                        text=(
                            f"⚖️ <b>La Corte ha emesso la sentenza!</b>\n\n"
                            f"<i>\"{confession.ai_roast}\"</i>\n\n"
                            f"Sul tuo segreto: <i>«{snippet}»</i>"
                        ),
                    )
                except Exception as exc:
                    logger.warning("Failed to notify author for confession id=%s: %s", cid, exc)

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
# AI pipeline & courtroom powers (with Escalation)
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
    base_cost: int,
    tx_type: TxType,
    field: str,
    duplicate_msg: str,
    runner: Callable[[_AgentInput], Awaitable[dict]],
) -> Confession:
    """Unlock (20 coins) or escalate (10 coins) Defense/Prosecution.

    LLM runs ONLY on 1st unlock and at escalation thresholds (5, 10); intermediate
    joiners execute in <30ms with zero LLM cost while incrementing the court tally.
    """
    with db_errors(session, f"invoke {label} agent"):
        confession = _get_active_confession(session, confession_id)
        _validate_confession_for_agent(confession, label)

        if user_id is not None and _has_user_voted_side(
            session, user_id, confession_id, tx_type
        ):
            raise _bad_request(duplicate_msg)

        counts = get_court_counts_map(session, [confession_id]).get(
            confession_id, (0, 0)
        )
        def_cnt = max(counts[0], 1 if confession.ai_defense else 0)
        pros_cnt = max(counts[1], 1 if confession.ai_prosecution else 0)

        already_unlocked = bool(getattr(confession, field))
        current_side_count = def_cnt if field == "ai_defense" else pros_cnt
        next_count = current_side_count + 1
        cost = COST_ESCALATE if already_unlocked else base_cost

        if user_id is not None:
            _ensure_can_afford(session, user_id, cost)

        needs_llm = (not already_unlocked) or (next_count in ESCALATION_AI_THRESHOLDS)
        new_text: Optional[str] = None

        if needs_llm:
            snapshot = _AgentInput(
                confession_id=confession_id,
                content=confession.content,
                ai_roast=confession.ai_roast or "",
                ai_defense=confession.ai_defense,
                escalation_count=next_count,
            )
            session.commit()

            result = await runner(snapshot)
            new_text = result.get(field)
            confession = _get_active_confession(session, confession_id)

        if user_id is not None:
            if needs_llm and _has_user_voted_side(
                session, user_id, confession_id, tx_type
            ):
                raise _bad_request(duplicate_msg)
            _charge_user(session, user_id, cost, tx_type, confession_id)

        if new_text:
            setattr(confession, field, new_text)

        new_def = next_count if field == "ai_defense" else def_cnt
        new_pros = next_count if field == "ai_prosecution" else pros_cnt
        _apply_court_badge(confession, new_def, new_pros)

        session.add(confession)
        session.commit()
        _refresh_if_expired(session, confession)

        # Invia notifica Telegram all'autore del segreto se difeso o accusato da altri
        if user_id != confession.author_id:
            try:
                action_title = "🛡️ Qualcuno ha invocato la tua Difesa!" if field == "ai_defense" else "⚔️ Qualcuno ha chiamato l'Accusa contro di te!"
                snippet = confession.content[:60] + "..." if len(confession.content) > 60 else confession.content
                await notify_confession_author(
                    session=session,
                    confession_id=confession_id,
                    text=(
                        f"<b>{action_title}</b>\n\n"
                        f"Il tuo segreto: <i>«{snippet}»</i> ha raggiunto {next_count} "
                        f"{'sostenitori' if field == 'ai_defense' else 'accusatori'} in Aula!"
                    ),
                )
            except Exception as exc:
                logger.warning("Failed to notify author for court action on confession id=%s: %s", confession_id, exc)

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
        base_cost=COST_DEFENSE,
        tx_type=TxType.BUY_AI_LAWYER,
        field="ai_defense",
        duplicate_msg="Hai già sostenuto la difesa per questo segreto.",
        runner=lambda inp: run_defense_agent(
            confession_id=inp.confession_id,
            content=inp.content,
            ai_roast=inp.ai_roast,
            escalation_count=inp.escalation_count,
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
        base_cost=COST_PROSECUTION,
        tx_type=TxType.BUY_AI_PROSECUTOR,
        field="ai_prosecution",
        duplicate_msg="Hai già accusato questo segreto.",
        runner=lambda inp: run_prosecution_agent(
            confession_id=inp.confession_id,
            content=inp.content,
            ai_roast=inp.ai_roast,
            ai_defense=inp.ai_defense,
            escalation_count=inp.escalation_count,
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
    """Single confession with reactions and courtroom escalation tallies."""
    confession = _get_active_confession(session, confession_id)
    court_counts = get_court_counts_map(session, [confession_id]).get(confession_id)

    user_reaction = None
    user_votes = None
    if current_user_id is not None:
        reactions = get_user_reactions_map(session, current_user_id, [confession_id])
        user_reaction = reactions.get(confession_id)
        user_votes = get_user_court_votes_map(
            session, current_user_id, [confession_id]
        ).get(confession_id)

    return serialize_confession(
        confession,
        user_reaction=user_reaction,
        current_user_id=current_user_id,
        court_counts=court_counts,
        user_votes=user_votes,
    )


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
        return f"sottovoce:feed:v{ver}:my:{current_user_id}:{limit}:{offset}"
    return f"sottovoce:feed:v{ver}:{feed_type}:{limit}:{offset}"


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
    ids = [c.id for c in confessions if c.id is not None]
    court_counts = get_court_counts_map(session, ids)
    items = [
        serialize_confession(c, court_counts=court_counts.get(c.id or -1))
        for c in confessions
    ]
    await set_cache(cache_key, items, ttl_seconds=FEED_CACHE_TTL_SECONDS)
    return items


async def get_feed_confessions_service(
    session: Session,
    feed_type: FeedType = "latest",
    limit: int = 20,
    offset: int = 0,
    current_user_id: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Feed with aggregate reactions/court tallies and current user's personal state."""
    with db_errors(session, "fetch feed"):
        items = await _load_feed_items(
            session, feed_type, limit, offset, current_user_id
        )

        reactions_by_confession: dict[int, Any] = {}
        votes_by_confession: dict[int, tuple[bool, bool]] = {}
        if current_user_id is not None and items:
            ids = [item["id"] for item in items if item.get("id") is not None]
            reactions_by_confession = get_user_reactions_map(session, current_user_id, ids)
            votes_by_confession = get_user_court_votes_map(session, current_user_id, ids)

        return [
            {
                **item,
                "user_reaction": reactions_by_confession.get(item["id"]),
                "user_defended": votes_by_confession.get(item["id"], (False, False))[0],
                "user_prosecuted": votes_by_confession.get(item["id"], (False, False))[1],
                "is_author": _is_author(item.get("author_id"), current_user_id),
            }
            for item in items
        ]
