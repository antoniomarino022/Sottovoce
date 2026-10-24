from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlmodel import Session

from config.database import get_session
from config.settings import settings
from src.schemas import (
    TelegramAuthRequest,
    UserResponse,
    UserTermsAcceptRequest,
)
from src.services import TelegramAuthService

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
)
async def register(
    request: Request,
    data: TelegramAuthRequest,
    checkbox: UserTermsAcceptRequest,
    response: Response,
    session: Session = Depends(get_session),
) -> UserResponse:
    """Authenticate Telegram Mini App user via signed initData and issue session cookie."""
    if not checkbox.accepted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="È necessario accettare i termini per continuare.",
        )

    user, created = TelegramAuthService.get_or_create_user(
        session=session,
        init_data_str=data.init_data,
        referral_code=data.referral_code,
    )

    if created:
        response.status_code = status.HTTP_201_CREATED

    is_https = request.url.scheme == "https" or settings.is_serverless
    response.set_cookie(
        key="sottovoce_session",
        value=user.user_key,
        httponly=True,
        secure=is_https,
        samesite="none" if is_https else "lax",
        max_age=86400 * 30,
    )

    return UserResponse.model_validate(user)
