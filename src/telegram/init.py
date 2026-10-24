import asyncio
from os import getenv

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from config.settings import settings

TOKEN = settings.TELEGRAM_BOT_TOKEN.get_secret_value()
WEBAPP_URL = settings.WEBAPP_URL or "https://sottovoce.vercel.app"

dp = Dispatcher()


# Command handler
@dp.message(Command("start"))
async def command_start_handler(message: Message) -> None:
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🤫 Apri Sottovoce",
                    web_app=WebAppInfo(url=WEBAPP_URL),
                )
            ]
        ]
    )
    await message.answer(
        "👋 **Benvenuto su Sottovoce!**\n\n"
        "La corte suprema delle confessioni anonime, giudicate senza pietà da un'intelligenza artificiale.\n\n"
        "Tocca il pulsante qui sotto per aprire la Mini App, leggere i segreti altrui e confessare i tuoi:",
        reply_markup=kb,
        parse_mode="Markdown",
    )


# Run the bot
async def main() -> None:
    bot = Bot(token=TOKEN)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
