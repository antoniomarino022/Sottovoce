from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from sqlmodel import Session

from config.database import get_session
from src.models import User
from src.models.enums import TriageCategory
from src.routers.deps import get_current_user
from src.schemas import ReportResponse
from src.services.report_service import create_report_service

router = APIRouter(prefix="/confessions/{confession_id}/reports", tags=["Reports"])


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


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Report a confession",
)
async def report_confession(
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
    raw_reason = payload.get("reason", "abuse")
    try:
        reason = TriageCategory(str(raw_reason))
    except ValueError:
        reason = TriageCategory.ABUSE

    if reason == TriageCategory.OK:
        reason = TriageCategory.ABUSE

    raw_details = payload.get("details")
    details = str(raw_details) if raw_details else None

    report, was_hidden = await create_report_service(
        session=session,
        confession_id=confession_id,
        reporter_id=current_user.id,
        reason=reason,
        details=details,
    )

    if request.headers.get("hx-request"):
        if was_hidden:
            return HTMLResponse(
                content=(
                    '<div class="bg-secondary rounded-xl p-4 text-center text-xs text-hint italic">'
                    "Questa confessione è stata rimossa dal feed in attesa di revisione."
                    "</div>"
                ),
                status_code=status.HTTP_200_OK,
            )
        return HTMLResponse(
            content='<span class="text-xs text-hint italic">✓ Segnalata</span>',
            status_code=status.HTTP_200_OK,
        )

    return ReportResponse(
        id=report.id,
        confession_id=report.confession_id,
        reporter_id=report.reporter_id,
        reason=report.reason,
        resolved=report.resolved,
        created_at=report.created_at,
    )
