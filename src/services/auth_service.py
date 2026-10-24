from datetime import datetime, timezone
import hashlib
import hmac
import secrets
import time
from typing import Optional

from aiogram.utils.web_app import safe_parse_webapp_init_data
from fastapi import HTTPException, status
from sqlmodel import Session, select

from config.settings import settings
from src.models import User, UserStatus


class TelegramAuthService:
    """Authentication service exclusively for Telegram Mini App (WebApp initData)."""

    # Maximum allowed age for initData (24 hours) to prevent replay attacks
    MAX_AUTH_AGE_SECONDS: int = 86400

    @classmethod
    def validate_and_extract_telegram_id(cls, init_data_str: str) -> tuple[int, Optional[str]]:
        """Validate the cryptographic HMAC signature of Telegram Mini App initData."""
        bot_token = settings.TELEGRAM_BOT_TOKEN.get_secret_value()
        if not bot_token:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="TELEGRAM_BOT_TOKEN is not configured on the server",
            )

        try:
            parsed_data = safe_parse_webapp_init_data(
                token=bot_token,
                init_data=init_data_str,
            )
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or forged Telegram initData signature",
            )

        auth_timestamp = parsed_data.auth_date.timestamp()
        if time.time() - auth_timestamp > cls.MAX_AUTH_AGE_SECONDS:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Telegram authentication data has expired",
            )

        if not parsed_data.user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User object missing from Telegram initData",
            )

        return parsed_data.user.id, parsed_data.start_param

    @classmethod
    def derive_user_key(cls, telegram_id: int) -> str:
        """Derive a one-way pseudonymous user_key using HMAC-SHA256 (Zero-PII)."""
        secret_key = settings.HMAC_SECRET_KEY.get_secret_value().encode("utf-8")
        telegram_id_bytes = str(telegram_id).encode("utf-8")
        return hmac.new(
            key=secret_key,
            msg=telegram_id_bytes,
            digestmod=hashlib.sha256,
        ).hexdigest()

    @classmethod
    def generate_unique_referral_code(cls, session: Session) -> str:
        """Generate a cryptographically secure, unique 8-character referral code."""
        for _ in range(10):
            candidate = f"HM{secrets.token_hex(3).upper()}"
            existing = session.exec(select(User).where(User.referral_code == candidate)).first()
            if not existing:
                return candidate
        return f"HM{secrets.token_hex(5).upper()}"

    @classmethod
    def get_or_create_user_by_telegram_id(
        cls,
        session: Session,
        telegram_id: int,
        referral_code: Optional[str] = None,
    ) -> tuple[User, bool]:
        """Resolve or register a user by telegram_id with Zero-PII protection."""
        user_key = cls.derive_user_key(telegram_id)

        user = session.exec(select(User).where(User.user_key == user_key)).first()
        if user:
            if user.status == UserStatus.BANNED:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"User account is banned. Reason: {user.ban_reason or 'Violation of terms'}",
                )
            return user, False

        referred_by_id = None
        if referral_code:
            referrer = session.exec(
                select(User).where(User.referral_code == referral_code.strip().upper())
            ).first()
            if referrer:
                referred_by_id = referrer.id

        user = User(
            user_key=user_key,
            status=UserStatus.ACTIVE,
            coins_balance=50,
            referral_code=cls.generate_unique_referral_code(session),
            referred_by_id=referred_by_id,
            terms_accepted_at=datetime.now(timezone.utc),
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return user, True

    @classmethod
    def get_or_create_user(
        cls,
        session: Session,
        init_data_str: str,
        referral_code: Optional[str] = None,
    ) -> tuple[User, bool]:
        """Authenticate a user via Telegram Mini App initData."""
        telegram_id, start_param = cls.validate_and_extract_telegram_id(init_data_str)
        effective_ref = referral_code or start_param
        return cls.get_or_create_user_by_telegram_id(
            session=session,
            telegram_id=telegram_id,
            referral_code=effective_ref,
        )
