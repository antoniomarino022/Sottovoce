from typing import Optional

from fastapi import Cookie, Depends, Header, HTTPException, status
from sqlmodel import Session, select

from config.database import get_session
from src.models import User, UserStatus
from src.services.auth_service import TelegramAuthService


def extract_raw_init_data(
    authorization: Optional[str] = Header(None, description="Format: 'tma <raw_init_data>'"),
    x_telegram_init_data: Optional[str] = Header(None, description="Telegram WebApp initData header"),
) -> Optional[str]:
    """Extract raw Telegram Mini App initData string from HTTP headers if present."""
    if x_telegram_init_data:
        return x_telegram_init_data.strip()

    if authorization and authorization.startswith("tma "):
        return authorization.replace("tma ", "", 1).strip()

    return None


async def get_current_user(
    raw_init_data: Optional[str] = Depends(extract_raw_init_data),
    hotmic_session: Optional[str] = Cookie(None, description="Mini App SSR session cookie"),
    session: Session = Depends(get_session),
) -> User:
    """Resolve the current Telegram Mini App user from signed initData (or SSR session cookie)."""
    if raw_init_data:
        user, _ = TelegramAuthService.get_or_create_user(
            session=session,
            init_data_str=raw_init_data,
        )
        return user

    if hotmic_session:
        user = session.exec(select(User).where(User.user_key == hotmic_session)).first()
        if user:
            if user.status == UserStatus.BANNED:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"User account is banned: {user.ban_reason or 'Violation of terms'}",
                )
            return user

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Accesso non autorizzato. Apri Hot-Mic da Telegram.",
    )


async def get_optional_current_user(
    raw_init_data: Optional[str] = Depends(extract_raw_init_data),
    hotmic_session: Optional[str] = Cookie(None),
    session: Session = Depends(get_session),
) -> Optional[User]:
    """Optional dependency for Mini App pages and public endpoints."""
    try:
        return await get_current_user(
            raw_init_data=raw_init_data,
            hotmic_session=hotmic_session,
            session=session,
        )
    except HTTPException:
        return None
