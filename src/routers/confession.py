from typing import Literal, Optional

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlmodel import Session

from config.database import get_session
from src.models import Confession, User
from src.routers.deps import get_current_user, get_optional_current_user
from src.schemas import ConfessionCreate, ConfessionResponse
from src.services.confession_service import (
    create_confession_service,
    delete_confession_service,
    get_confession_by_id_service,
    get_feed_confessions_service,
    get_user_reactions_map,
    invoke_defense_service,
    invoke_prosecution_service,
    serialize_confession,
)
from src.templates import templates

router = APIRouter(prefix="/confessions", tags=["Confessions"])


def get_current_user_id(user: User = Depends(get_current_user)) -> int:
    if user.id is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Authenticated user must have a valid identifier",
        )
    return user.id


def _is_htmx(request: Request) -> bool:
    return bool(request.headers.get("hx-request"))


def _render_card(
    request: Request,
    session: Session,
    confession: Confession,
    user: User,
) -> Response:
    """Render the updated confession card directly without re-querying Confession/User."""
    user_state = sa.inspect(user, raiseerr=False)
    if user_state is not None and user_state.expired:
        try:
            session.refresh(user)
        except Exception:
            pass

    user_reaction = None
    if user.id is not None and confession.id is not None:
        reactions = get_user_reactions_map(session, user.id, [confession.id])
        user_reaction = reactions.get(confession.id)

    c_dict = serialize_confession(
        confession,
        user_reaction=user_reaction,
        current_user_id=user.id,
    )
    response = templates.TemplateResponse(
        request=request,
        name="partials/confession_card.html",
        context={"c": c_dict, "user": user},
    )
    response.headers["Vary"] = "HX-Request"
    return response


@router.post(
    "/",
    response_model=ConfessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new anonymous confession",
)
async def create_confession(
    data: ConfessionCreate,
    user_id: int = Depends(get_current_user_id),
    session: Session = Depends(get_session),
) -> ConfessionResponse:
    confession = await create_confession_service(
        session=session, author_id=user_id, data=data
    )
    return ConfessionResponse.model_validate(confession)


@router.get(
    "/",
    response_model=list[ConfessionResponse],
    summary="Get confessions feed",
)
async def get_confessions_feed(
    feed_type: Literal["latest", "popular", "my"] = Query("latest"),
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    current_user: Optional[User] = Depends(get_optional_current_user),
    session: Session = Depends(get_session),
) -> list[ConfessionResponse]:
    items = await get_feed_confessions_service(
        session=session,
        feed_type=feed_type,
        limit=limit,
        offset=offset,
        current_user_id=current_user.id if current_user else None,
    )
    return [ConfessionResponse.model_validate(item) for item in items]


@router.get(
    "/{id}",
    response_model=ConfessionResponse,
    summary="Get single confession",
)
async def get_confession(
    id: int,
    current_user: Optional[User] = Depends(get_optional_current_user),
    session: Session = Depends(get_session),
) -> ConfessionResponse:
    item = await get_confession_by_id_service(
        session=session,
        confession_id=id,
        current_user_id=current_user.id if current_user else None,
    )
    return ConfessionResponse.model_validate(item)


@router.delete(
    "/{id}",
    summary="Delete confession",
)
async def delete_confession(
    request: Request,
    id: int,
    user_id: int = Depends(get_current_user_id),
    session: Session = Depends(get_session),
):
    res = await delete_confession_service(session=session, author_id=user_id, id=id)
    if _is_htmx(request):
        return Response(content="", status_code=status.HTTP_200_OK)
    return res


@router.post(
    "/{id}/defense",
    summary="Invoke defense attorney agent",
)
async def invoke_defense(
    request: Request,
    id: int,
    current_user: User = Depends(get_current_user),
    user_id: int = Depends(get_current_user_id),
    session: Session = Depends(get_session),
):
    confession = await invoke_defense_service(
        session=session, confession_id=id, user_id=user_id
    )
    if _is_htmx(request):
        return _render_card(request, session, confession, current_user)
    return ConfessionResponse.model_validate(confession)


@router.post(
    "/{id}/prosecution",
    summary="Invoke prosecutor agent",
)
async def invoke_prosecution(
    request: Request,
    id: int,
    current_user: User = Depends(get_current_user),
    user_id: int = Depends(get_current_user_id),
    session: Session = Depends(get_session),
):
    confession = await invoke_prosecution_service(
        session=session, confession_id=id, user_id=user_id
    )
    if _is_htmx(request):
        return _render_card(request, session, confession, current_user)
    return ConfessionResponse.model_validate(confession)
