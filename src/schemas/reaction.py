from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from src.models.enums import ReactionType


class ReactionCreateRequest(BaseModel):
    """Richiesta inviata dal client per aggiungere o modificare una reazione."""
    type: ReactionType = Field(
        ...,
        description="Tipologia di reazione selezionata (skull, disagio, popcorn, clown)",
    )


class ReactionCreate(BaseModel):
    """Schema per la persistenza a database di una reazione."""
    confession_id: int = Field(..., description="ID della confessione target")
    user_id: int = Field(..., description="ID dell'utente votante")
    type: ReactionType = Field(..., description="Tipo di reazione")


class ReactionResponse(BaseModel):
    """Risposta con lo stato della reazione e i contatori aggiornati."""
    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
    confession_id: int
    user_id: int
    type: ReactionType
    created_at: datetime

    # Contatori aggiornati per facilitare il re-rendering via HTMX
    count_skull: Optional[int] = None
    count_disagio: Optional[int] = None
    count_popcorn: Optional[int] = None
    count_clown: Optional[int] = None
    total_reactions: Optional[int] = None


class ReactionToggleResponse(BaseModel):
    """Risposta a un'azione di toggle/creazione/rimozione reazione."""
    action: str = Field(..., description="Azione eseguita: 'created', 'updated', o 'removed'")
    confession_id: int
    reaction: Optional[ReactionResponse] = None
    count_skull: int
    count_disagio: int
    count_popcorn: int
    count_clown: int
    total_reactions: int


class ConfessionReactionsSummary(BaseModel):
    """Riepilogo delle reazioni e contatori per una determinata confessione."""
    confession_id: int
    count_skull: int
    count_disagio: int
    count_popcorn: int
    count_clown: int
    total_reactions: int
    user_reaction: Optional[ReactionType] = None
