from datetime import datetime, timezone
import re
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.models.enums import UserStatus


class TelegramAuthRequest(BaseModel):
    """Richiesta di autenticazione da Telegram Mini App."""

    init_data: str = Field(
        ...,
        min_length=10,
        description="Stringa grezza 'initData' firmata da Telegram WebApp",
    )
    referral_code: Optional[str] = Field(
        default=None,
        min_length=6,
        max_length=16,
        description="Codice referral opzionale dell'invitante",
    )

    @field_validator("referral_code")
    @classmethod
    def clean_referral_code(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip().upper()
            if not re.match(r"^[A-Z0-9_-]{6,16}$", v):
                raise ValueError("Il codice referral deve contenere tra 6 e 16 caratteri alfanumerici")
        return v


class UserTermsAcceptRequest(BaseModel):
    """Richiesta di accettazione termini e condizioni della Mini App."""

    accepted: bool = Field(
        ...,
        description="Flag di accettazione delle condizioni d'uso e privacy",
    )

    @field_validator("accepted")
    @classmethod
    def must_be_accepted(cls, v: bool) -> bool:
        if not v:
            raise ValueError("È necessario accettare i termini per continuare")
        return v


class UserCreate(BaseModel):
    """Schema per la creazione interna di un nuovo utente nel database."""

    user_key: str = Field(
        ...,
        min_length=64,
        max_length=64,
        description="Hash HMAC-SHA256 (64 caratteri esadecimali)",
    )
    referral_code: str = Field(
        ...,
        min_length=6,
        max_length=16,
        description="Codice referral generato univoco per l'utente",
    )
    referred_by_id: Optional[int] = Field(
        default=None,
        description="ID dell'utente che ha effettuato l'invito",
    )
    terms_accepted_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Data e ora di accettazione dei termini di servizio",
    )
    coins_balance: int = Field(
        default=50,
        ge=0,
        description="Saldo iniziale monete (default: 50)",
    )
    trust_score: int = Field(
        default=100,
        ge=0,
        description="Punteggio reputazione iniziale",
    )
    status: UserStatus = Field(
        default=UserStatus.ACTIVE,
        description="Stato iniziale dell'account",
    )

    @field_validator("user_key")
    @classmethod
    def validate_user_key(cls, v: str) -> str:
        v = v.strip().lower()
        if len(v) != 64 or not re.match(r"^[0-9a-f]{64}$", v):
            raise ValueError("user_key deve essere un hash esadecimale SHA-256 valido di 64 caratteri")
        return v

    @field_validator("referral_code")
    @classmethod
    def validate_referral_code(cls, v: str) -> str:
        v = v.strip().upper()
        if not re.match(r"^[A-Z0-9_-]{6,16}$", v):
            raise ValueError("referral_code non valido")
        return v


class UserStatusUpdateRequest(BaseModel):
    """Richiesta di aggiornamento stato utente (moderazione / ban)."""

    status: UserStatus = Field(
        ...,
        description="Nuovo stato dell'account",
    )
    ban_reason: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Motivo del ban o sospensione",
    )
    banned_until: Optional[datetime] = Field(
        default=None,
        description="Scadenza temporale del ban (se temporaneo)",
    )


class UserResponse(BaseModel):
    """Schema di risposta pubblico per il profilo dell'utente."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_key: str
    status: UserStatus
    coins_balance: int
    referral_code: str
    referred_by_id: Optional[int] = None
    referral_qualified_at: Optional[datetime] = None
    trust_score: int
    last_post_at: Optional[datetime] = None
    terms_accepted_at: datetime
    created_at: datetime
