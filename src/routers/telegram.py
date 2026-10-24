import logging
from typing import Any

from aiogram import Bot
from aiogram.types import Update
from fastapi import APIRouter, Header, HTTPException, Request, status

from config.settings import settings
from src.telegram.init import dp

logger = logging.getLogger("sottovoce.telegram.webhook")
router = APIRouter(prefix="/telegram", tags=["Telegram Bot Webhook"])

_bot_instance: Bot | None = None


def get_bot() -> Bot:
    """Retrieve or create bot instance for webhook request handling."""
    global _bot_instance
    if _bot_instance is None:
        token = settings.TELEGRAM_BOT_TOKEN.get_secret_value()
        _bot_instance = Bot(token=token)
    return _bot_instance


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(None),
) -> dict[str, Any]:
    """FastAPI webhook endpoint for Telegram bot updates (used in Vercel/Production)."""
    try:
        raw_json = await request.json()
        bot = get_bot()
        update = Update.model_validate(raw_json, context={"bot": bot})
        await dp.feed_update(bot, update)
        return {"ok": True}
    except Exception as exc:
        logger.error("Error processing Telegram webhook update: %s", exc)
        return {"ok": False, "error": str(exc)}


@router.get("/webhook/set", status_code=status.HTTP_200_OK)
async def set_telegram_webhook() -> dict[str, Any]:
    """Utility endpoint to register the webhook URL with Telegram Bot API."""
    webhook_url = settings.TELEGRAM_WEBHOOK_URL
    if not webhook_url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="TELEGRAM_WEBHOOK_URL is not configured in settings",
        )

    bot = get_bot()
    endpoint = f"{webhook_url.rstrip('/')}/telegram/webhook"
    success = await bot.set_webhook(url=endpoint)
    info = await bot.get_webhook_info()
    return {"success": success, "webhook_url": endpoint, "info": info.model_dump()}


@router.get("/webhook/info", status_code=status.HTTP_200_OK)
async def get_telegram_webhook_info() -> dict[str, Any]:
    """Retrieve current Telegram webhook status."""
    bot = get_bot()
    info = await bot.get_webhook_info()
    return {"info": info.model_dump()}
