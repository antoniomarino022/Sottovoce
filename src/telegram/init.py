import asyncio

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from config.settings import settings

TOKEN = settings.TELEGRAM_BOT_TOKEN.get_secret_value()
WEBAPP_URL = settings.WEBAPP_URL.strip()

dp = Dispatcher()


@dp.message(CommandStart())
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
        "👋 <b>Benvenuto su Sottovoce!</b>\n\n"
        "La corte suprema delle confessioni anonime, giudicate senza pietà da un'intelligenza artificiale.\n\n"
        "Tocca il pulsante qui sotto per aprire la Mini App, leggere i segreti altrui e confessare i tuoi:",
        reply_markup=kb,
        parse_mode="HTML",
    )


async def main() -> None:
    async with Bot(token=TOKEN) as bot:
        await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
