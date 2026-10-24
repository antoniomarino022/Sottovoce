import sys

# On Windows, psycopg async requires SelectorEventLoop instead of ProactorEventLoop
if sys.platform == "win32":
    import asyncio
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

import asyncio
from contextlib import asynccontextmanager
import logging
from pathlib import Path

import anyio
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware

from config.database import init_db
from config.settings import settings
from src.routers import (
    ad_router,
    auth_router,
    confession_router,
    leaderboard_router,
    pages_router,
    reaction_router,
    report_router,
    telegram_router,
)

logger = logging.getLogger("sottovoce")
logging.basicConfig(level=logging.INFO)


class CachedStaticFiles(StaticFiles):
    """StaticFiles with Cache-Control headers for browser and Telegram WebView caching."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=86400"
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize local dev resources on startup and cleanly close pools on shutdown.

    On Vercel Serverless, schema creation is handled by Alembic migrations (`alembic upgrade head`)
    to avoid slowing down cold starts with DDL queries.
    """
    if not settings.is_serverless:
        async def _run_local_db_init():
            try:
                await anyio.to_thread.run_sync(init_db)
                logger.info("Database tables verified.")
            except Exception as exc:
                logger.warning("Local/Neon DB not reachable on startup: %s", exc)

        asyncio.create_task(_run_local_db_init())

    try:
        from src.agents.memory import init_checkpointer
        await init_checkpointer()
        logger.info("LangGraph PostgreSQL checkpointer pool ready.")
    except Exception as exc:
        logger.warning("Checkpointer using in-memory fallback: %s", exc)

    yield

    try:
        from src.agents.memory import close_checkpointer
        await close_checkpointer()
    except Exception:
        pass


app = FastAPI(
    title="Sottovoce",
    description="Telegram Mini App di confessioni anonime con Tribunale satirico AI",
    version="0.1.0",
    lifespan=lifespan,
)

# Gzip compression for HTML, CSS, JS, and JSON responses > 500 bytes
app.add_middleware(GZipMiddleware, minimum_size=500)

# Static assets with 1-day Cache-Control
_STATIC_DIR = Path(__file__).resolve().parent / "src" / "static"
app.mount("/static", CachedStaticFiles(directory=str(_STATIC_DIR)), name="static")

# UI Pages (SSR + HTMX partials) & JSON API Routers
app.include_router(pages_router)
app.include_router(auth_router)
app.include_router(confession_router)
app.include_router(reaction_router)
app.include_router(report_router)
app.include_router(telegram_router)
app.include_router(leaderboard_router)
app.include_router(ad_router)


@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "app": "Sottovoce"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
