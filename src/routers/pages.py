from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from config.database import get_session
from config.settings import settings
from src.models import User
from src.routers.deps import get_optional_current_user
from src.services.confession_service import get_feed_confessions_service
from src.services.leaderboard_service import (
    get_top_secrets_weekly,
)
from src.templates import templates

router = APIRouter(tags=["Pages"])


def _render_template(
    request: Request,
    name: str,
    context: dict[str, Any],
) -> HTMLResponse:
    """Render a Jinja2 template with shared Mini App config and HTMX Vary headers."""
    merged_context = {
        "bot_username": settings.TELEGRAM_BOT_USERNAME,
        "BLOCK_ID": getattr(settings, "BLOCK_ID", settings.BLOCK_ID),
        **context,
    }
    resp = templates.TemplateResponse(
        request=request,
        name=name,
        context=merged_context,
    )
    resp.headers["Vary"] = "HX-Request, HX-Target"
    return resp


@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    filter: str = "latest",
    current_user: Optional[User] = Depends(get_optional_current_user),
    session: Session = Depends(get_session),
):
    """Home page: renders the confessions feed (or partial list for HTMX filter tabs)."""
    if not current_user:
        return RedirectResponse(url="/register", status_code=302)

    feed_type = filter if filter in ("latest", "popular", "my") else "latest"
    confessions = await get_feed_confessions_service(
        session=session,
        feed_type=feed_type,  # type: ignore[arg-type]
        limit=30,
        current_user_id=current_user.id,
    )

    is_filter_swap = (
        request.headers.get("hx-request")
        and request.headers.get("hx-target") == "feed-list"
    )
    template_name = "partials/feed_list.html" if is_filter_swap else "feed.html"

    return _render_template(
        request,
        template_name,
        {
            "confessions": confessions,
            "user": current_user,
            "filter": feed_type,
        },
    )


@router.get("/leaderboard", response_class=HTMLResponse)
async def leaderboard_page(
    request: Request,
    current_user: Optional[User] = Depends(get_optional_current_user),
    session: Session = Depends(get_session),
):
    """Weekly leaderboard page (Top 10 Secrets)."""
    if not current_user:
        return RedirectResponse(url="/register", status_code=302)

    items = await get_top_secrets_weekly(session=session, limit=10, days=7)

    is_tab_swap = (
        request.headers.get("hx-request")
        and request.headers.get("hx-target") == "leaderboard-list"
    )
    template_name = (
        "partials/leaderboard_list.html" if is_tab_swap else "leaderboard.html"
    )

    return _render_template(
        request,
        template_name,
        {
            "items": items,
            "user": current_user,
        },
    )


@router.get("/confession", response_class=HTMLResponse)
async def confession_page(
    request: Request,
    current_user: Optional[User] = Depends(get_optional_current_user),
):
    """Confession creation page."""
    if not current_user:
        return RedirectResponse(url="/register", status_code=302)

    return _render_template(
        request,
        "confession.html",
        {"user": current_user},
    )


@router.get("/register", response_class=HTMLResponse)
async def register_page(
    request: Request,
    current_user: Optional[User] = Depends(get_optional_current_user),
):
    """Telegram Mini App onboarding and terms acceptance gate."""
    if current_user:
        return RedirectResponse(url="/", status_code=302)

    return _render_template(
        request,
        "register.html",
        {},
    )
