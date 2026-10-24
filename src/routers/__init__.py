from src.routers.ad import router as ad_router
from src.routers.auth import router as auth_router
from src.routers.confession import router as confession_router
from src.routers.deps import (
    extract_raw_init_data,
    get_current_user,
    get_optional_current_user,
)
from src.routers.leaderboard import router as leaderboard_router
from src.routers.pages import router as pages_router
from src.routers.reaction import router as reaction_router
from src.routers.report import router as report_router
from src.routers.telegram import router as telegram_router

__all__ = [
    "ad_router",
    "auth_router",
    "confession_router",
    "reaction_router",
    "report_router",
    "telegram_router",
    "leaderboard_router",
    "pages_router",
    "extract_raw_init_data",
    "get_current_user",
    "get_optional_current_user",
]
