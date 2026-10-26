import asyncio
import logging
from typing import Optional

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from sqlmodel import Session, select

from config.settings import settings
from src.models import Confession, User

logger = logging.getLogger("sottovoce.telegram.notifications")




def _get_webapp_markup(path: str = "") -> Optional[InlineKeyboardMarkup]:
    webapp_url = settings.WEBAPP_URL.strip()
    if not webapp_url:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🤫 Apri Sottovoce",
                    web_app=WebAppInfo(url=webapp_url),
                )
            ]
        ]
    )


async def send_telegram_notification(
    telegram_id: int,
    text: str,
    *,
    webapp_path: str = "",
) -> bool:
    """Send a native notification message to a user via the Telegram Bot."""
    token = settings.TELEGRAM_BOT_TOKEN.get_secret_value()
    if not token or not telegram_id:
        return False

    try:
        markup = _get_webapp_markup(webapp_path)
        async with Bot(token=token) as bot:
            await bot.send_message(
                chat_id=telegram_id,
                text=text,
                parse_mode="HTML",
                reply_markup=markup,
            )
        return True
    except Exception as exc:
        logger.warning(
            "Could not send Telegram notification to user %s: %s", telegram_id, exc
        )
        return False


async def notify_confession_author(
    session: Session,
    confession_id: int,
    text: str,
    *,
    webapp_path: str = "",
) -> None:
    """Helper to look up author of a confession and send them a notification in background."""
    try:
        confession = session.get(Confession, confession_id)
        if not confession or not confession.author_id:
            return

        author = session.get(User, confession.author_id)
        if not author or not author.telegram_id:
            return

        asyncio.create_task(
            send_telegram_notification(
                telegram_id=author.telegram_id,
                text=text,
                webapp_path=webapp_path,
            )
        )
    except Exception as exc:
        logger.warning("Error preparing author notification: %s", exc)
