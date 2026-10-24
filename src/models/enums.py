import enum
import sqlalchemy as sa


class UserStatus(str, enum.Enum):
    ACTIVE = "active"
    SHADOWBANNED = "shadowbanned"
    SUSPENDED = "suspended"
    BANNED = "banned"


class ModerationStatus(str, enum.Enum):
    PENDING_AI = "pending_ai"
    APPROVED = "approved"
    CRISIS_HELD = "crisis_held"
    UNDER_REVIEW = "under_review"
    REJECTED = "rejected"


class TriageCategory(str, enum.Enum):
    OK = "ok"
    SELF_HARM = "self_harm"
    VIOLENCE = "violence"
    ABUSE = "abuse"
    DOXXING = "doxxing"
    HATE_SPEECH = "hate_speech"
    ILLEGAL = "illegal"
    SPAM = "spam"


class ReactionType(str, enum.Enum):
    SKULL = "skull"
    DISAGIO = "disagio"
    POPCORN = "popcorn"
    CLOWN = "clown"


class PostStyle(str, enum.Enum):
    STANDARD = "standard"
    NEON_CYBER = "neon_cyber"
    GOLD_GLITCH = "gold_glitch"


class ShameBadge(str, enum.Enum):
    NONE = "none"
    CERTIFIED_CLOWN = "certified_clown"
    WALKING_RED_FLAG = "walking_red_flag"
    TOUCH_GRASS = "touch_grass"


class TxType(str, enum.Enum):
    STARS_PURCHASE = "stars_purchase"
    REFERRAL_BONUS = "referral_bonus"
    WEEKLY_PODIUM = "weekly_podium"
    BUY_HIGHLIGHT = "buy_highlight"
    BUY_PIN_BOOST = "buy_pin_boost"
    BUY_AI_LAWYER = "buy_ai_lawyer"
    BUY_AI_PROSECUTOR = "buy_ai_prosecutor"
    BUY_SHAME_STAMP = "buy_shame_stamp"
    AD_REWARD = "ad_reward"


def pg_enum(enum_cls: type[enum.Enum], name: str) -> sa.Enum:
    """Helper to generate a native PostgreSQL ENUM with exact lowercase values."""
    return sa.Enum(
        enum_cls,
        name=name,
        values_callable=lambda obj: [e.value for e in obj],
        native_enum=True,
    )
