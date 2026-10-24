import logging
from typing import Any

from aiogram import Bot
from aiogram.types import Update
from fastapi import APIRouter, Header, HTTPException, Request, status

from config.settings import settings
from src.telegram.init import dp

logger = logging.getLogger("sottovoce.telegram.webhook")
router = APIRouter(prefix="/telegram", tags=["Telegram Bot Webhook"])


def _get_bot_token() -> str:
    token = settings.TELEGRAM_BOT_TOKEN.get_secret_value().strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="TELEGRAM_BOT_TOKEN is not configured in settings",
        )
    return token


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(None),
) -> dict[str, Any]:
    """FastAPI webhook endpoint for Telegram bot updates (safe across serverless event loops)."""
    try:
        raw_json = await request.json()
        async with Bot(token=_get_bot_token()) as bot:
            update = Update.model_validate(raw_json, context={"bot": bot})
            await dp.feed_update(bot, update)
        return {"ok": True}
    except Exception as exc:
        logger.error("Error processing Telegram webhook update: %s", exc)
        return {"ok": False, "error": str(exc)}


@router.get("/webhook/set", status_code=status.HTTP_200_OK)
async def set_telegram_webhook(request: Request) -> dict[str, Any]:
    """Register the webhook URL with Telegram Bot API."""
    webhook_url = settings.TELEGRAM_WEBHOOK_URL.strip() or f"{request.url.scheme}://{request.url.netloc}"
    base_url = webhook_url.rstrip("/")
    endpoint = (
        base_url
        if base_url.endswith("/telegram/webhook")
        else f"{base_url}/telegram/webhook"
    )

    async with Bot(token=_get_bot_token()) as bot:
        success = await bot.set_webhook(url=endpoint, drop_pending_updates=False)
        info = await bot.get_webhook_info()
    return {"success": success, "webhook_url": endpoint, "info": info.model_dump()}


@router.get("/webhook/info", status_code=status.HTTP_200_OK)
async def get_telegram_webhook_info() -> dict[str, Any]:
    """Retrieve current Telegram webhook status."""
    async with Bot(token=_get_bot_token()) as bot:
        info = await bot.get_webhook_info()
    return {"info": info.model_dump()}
