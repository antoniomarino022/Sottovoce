import logging
from typing import Any, Optional, Tuple

import sqlalchemy as sa
from fastapi import HTTPException, status
from sqlmodel import Session, select

from src.models import Confession, Reaction
from src.models.enums import ReactionType
from src.services.notification_service import notify_confession_author

logger = logging.getLogger("sottovoce.reaction_service")


def _refresh_if_expired(session: Session, obj: Any) -> None:
    state = sa.inspect(obj, raiseerr=False)
    if state is not None and state.expired:
        session.refresh(obj)


def _adjust_reaction_counter(confession: Confession, r_type: ReactionType, delta: int) -> None:
    """Safely increment or decrement the appropriate reaction counter on the confession."""
    if r_type == ReactionType.SKULL:
        confession.count_skull = max(0, confession.count_skull + delta)
    elif r_type == ReactionType.DISAGIO:
        confession.count_disagio = max(0, confession.count_disagio + delta)
    elif r_type == ReactionType.POPCORN:
        confession.count_popcorn = max(0, confession.count_popcorn + delta)
    elif r_type == ReactionType.CLOWN:
        confession.count_clown = max(0, confession.count_clown + delta)


def get_confession_or_404(session: Session, confession_id: int) -> Confession:
    """Retrieve active (non-deleted) confession or raise 404."""
    confession = session.get(Confession, confession_id)
    if not confession or confession.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Confession not found",
        )
    return confession


async def create_or_toggle_reaction_service(
    session: Session,
    confession_id: int,
    user_id: int,
    reaction_type: ReactionType,
) -> Tuple[Optional[Reaction], Confession, str]:
    """Toggle, switch, or create a user's reaction without global Redis cache thrashing."""
    try:
        confession = get_confession_or_404(session, confession_id)

        existing_reaction = session.exec(
            select(Reaction).where(
                Reaction.confession_id == confession_id,
                Reaction.user_id == user_id,
            )
        ).first()

        if existing_reaction:
            if existing_reaction.type == reaction_type:
                _adjust_reaction_counter(confession, existing_reaction.type, -1)
                session.delete(existing_reaction)
                session.add(confession)
                session.commit()
                _refresh_if_expired(session, confession)
                return None, confession, "removed"

            _adjust_reaction_counter(confession, existing_reaction.type, -1)
            _adjust_reaction_counter(confession, reaction_type, 1)
            existing_reaction.type = reaction_type
            session.add(existing_reaction)
            session.add(confession)
            session.commit()
            _refresh_if_expired(session, existing_reaction)
            _refresh_if_expired(session, confession)
            return existing_reaction, confession, "updated"

        new_reaction = Reaction(
            confession_id=confession_id,
            user_id=user_id,
            type=reaction_type,
        )
        _adjust_reaction_counter(confession, reaction_type, 1)
        session.add(new_reaction)
        session.add(confession)
        session.commit()
        _refresh_if_expired(session, new_reaction)
        _refresh_if_expired(session, confession)

        # Notifica Telegram all'autore per nuova reazione
        if user_id != confession.author_id:
            emoji_map = {
                ReactionType.SKULL: "💀",
                ReactionType.DISAGIO: "🫠",
                ReactionType.POPCORN: "🍿",
                ReactionType.CLOWN: "🤡",
            }
            emoji = emoji_map.get(reaction_type, "✨")
            tot = confession.total_reactions or (
                confession.count_skull
                + confession.count_disagio
                + confession.count_popcorn
                + confession.count_clown
            )
            snippet = confession.content[:60] + "..." if len(confession.content) > 60 else confession.content
            await notify_confession_author(
                session=session,
                confession_id=confession_id,
                text=(
                    f"{emoji} <b>Nuova reazione ricevuta!</b>\n\n"
                    f"Qualcuno ha reagito con {emoji} al tuo segreto: <i>«{snippet}»</i>\n"
                    f"Totale voti ricevuti: <b>{tot}</b>"
                ),
            )

        return new_reaction, confession, "created"

    except HTTPException:
        raise
    except Exception as exc:
        session.rollback()
        logger.error("Error setting reaction for confession %s, user %s: %s", confession_id, user_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process reaction: {str(exc)}",
        )


async def get_user_reaction_service(
    session: Session,
    confession_id: int,
    user_id: int,
) -> Optional[Reaction]:
    """Retrieve the reaction of a specific user for a confession."""
    get_confession_or_404(session, confession_id)
    return session.exec(
        select(Reaction).where(
            Reaction.confession_id == confession_id,
            Reaction.user_id == user_id,
        )
    ).first()


async def get_confession_reactions_service(
    session: Session,
    confession_id: int,
    user_id: Optional[int] = None,
) -> dict:
    """Retrieve reaction statistics and optional active reaction of current user."""
    confession = get_confession_or_404(session, confession_id)

    user_reaction = None
    if user_id is not None:
        user_reaction = session.exec(
            select(Reaction.type).where(
                Reaction.confession_id == confession_id,
                Reaction.user_id == user_id,
            )
        ).first()

    total = (
        confession.count_skull
        + confession.count_disagio
        + confession.count_popcorn
        + confession.count_clown
    )

    return {
        "confession_id": confession.id,
        "count_skull": confession.count_skull,
        "count_disagio": confession.count_disagio,
        "count_popcorn": confession.count_popcorn,
        "count_clown": confession.count_clown,
        "total_reactions": total,
        "user_reaction": user_reaction,
    }


async def delete_reaction_service(
    session: Session,
    confession_id: int,
    user_id: int,
) -> Confession:
    """Explicitly delete user reaction from a confession."""
    try:
        confession = get_confession_or_404(session, confession_id)

        existing_reaction = session.exec(
            select(Reaction).where(
                Reaction.confession_id == confession_id,
                Reaction.user_id == user_id,
            )
        ).first()

        if not existing_reaction:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Reaction not found",
            )

        _adjust_reaction_counter(confession, existing_reaction.type, -1)
        session.delete(existing_reaction)
        session.add(confession)
        session.commit()
        _refresh_if_expired(session, confession)
        return confession

    except HTTPException:
        raise
    except Exception as exc:
        session.rollback()
        logger.error("Error deleting reaction for confession %s, user %s: %s", confession_id, user_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete reaction: {str(exc)}",
        )
