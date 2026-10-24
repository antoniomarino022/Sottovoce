from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlmodel import Session

from config.database import get_session
from src.models import User
from src.models.enums import ReactionType
from src.routers.deps import get_current_user, get_optional_current_user
from src.schemas import (
    ConfessionReactionsSummary,
    ReactionResponse,
    ReactionToggleResponse,
)
from src.services.confession_service import serialize_confession
from src.services.reaction_service import (
    create_or_toggle_reaction_service,
    delete_reaction_service,
    get_confession_reactions_service,
    get_user_reaction_service,
)
from src.templates import templates

router = APIRouter(prefix="/confessions/{confession_id}/reactions", tags=["Reactions"])


async def _parse_request_dict(request: Request) -> dict[str, Any]:
    """Read either JSON or URL-encoded form payload (supports both API & HTMX hx-vals)."""
    if "application/json" in request.headers.get("content-type", ""):
        try:
            body = await request.json()
            return body if isinstance(body, dict) else {}
        except Exception:
            return {}
    form = await request.form()
    return dict(form)


@router.post("", status_code=status.HTTP_200_OK)
async def toggle_reaction(
    request: Request,
    confession_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if current_user.id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Utente non autenticato",
        )

    payload = await _parse_request_dict(request)
    raw_val = payload.get("type")
    if not raw_val:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Tipo di reazione mancante",
        )

    try:
        r_type = ReactionType(str(raw_val))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Tipo di reazione non valido",
        )

    reaction, confession, action = await create_or_toggle_reaction_service(
        session=session,
        confession_id=confession_id,
        user_id=current_user.id,
        reaction_type=r_type,
    )

    if request.headers.get("hx-request"):
        c_dict = serialize_confession(
            confession,
            user_reaction=reaction.type if reaction else None,
            current_user_id=current_user.id,
        )
        target = request.headers.get("hx-target") or ""
        template_name = (
            "partials/reaction_bar.html"
            if "reaction-bar" in target
            else "partials/confession_card.html"
        )
        response = templates.TemplateResponse(
            request=request,
            name=template_name,
            context={"c": c_dict, "user": current_user},
        )
        response.headers["Vary"] = "HX-Request, HX-Target"
        return response

    total = (
        confession.count_skull
        + confession.count_disagio
        + confession.count_popcorn
        + confession.count_clown
    )

    reaction_resp = None
    if reaction:
        reaction_resp = ReactionResponse.model_validate(reaction)
        reaction_resp.count_skull = confession.count_skull
        reaction_resp.count_disagio = confession.count_disagio
        reaction_resp.count_popcorn = confession.count_popcorn
        reaction_resp.count_clown = confession.count_clown
        reaction_resp.total_reactions = total

    return ReactionToggleResponse(
        action=action,
        confession_id=confession_id,
        reaction=reaction_resp,
        count_skull=confession.count_skull,
        count_disagio=confession.count_disagio,
        count_popcorn=confession.count_popcorn,
        count_clown=confession.count_clown,
        total_reactions=total,
    )


@router.get(
    "",
    response_model=ConfessionReactionsSummary,
    status_code=status.HTTP_200_OK,
)
async def get_reactions(
    confession_id: int,
    current_user: Optional[User] = Depends(get_optional_current_user),
    session: Session = Depends(get_session),
) -> ConfessionReactionsSummary:
    user_id = current_user.id if current_user else None
    stats = await get_confession_reactions_service(
        session=session,
        confession_id=confession_id,
        user_id=user_id,
    )
    return ConfessionReactionsSummary.model_validate(stats)


@router.get(
    "/me",
    response_model=ReactionResponse,
    status_code=status.HTTP_200_OK,
)
async def get_my_reaction(
    confession_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> ReactionResponse:
    if current_user.id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Utente non autenticato",
        )

    reaction = await get_user_reaction_service(
        session=session,
        confession_id=confession_id,
        user_id=current_user.id,
    )
    if not reaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nessuna reazione trovata per questa confessione",
        )

    return ReactionResponse.model_validate(reaction)


@router.delete(
    "",
    response_model=ConfessionReactionsSummary,
    status_code=status.HTTP_200_OK,
)
async def delete_reaction(
    confession_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> ConfessionReactionsSummary:
    if current_user.id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Utente non autenticato",
        )

    confession = await delete_reaction_service(
        session=session,
        confession_id=confession_id,
        user_id=current_user.id,
    )

    total = (
        confession.count_skull
        + confession.count_disagio
        + confession.count_popcorn
        + confession.count_clown
    )

    return ConfessionReactionsSummary(
        confession_id=confession_id,
        count_skull=confession.count_skull,
        count_disagio=confession.count_disagio,
        count_popcorn=confession.count_popcorn,
        count_clown=confession.count_clown,
        total_reactions=total,
        user_reaction=None,
    )
