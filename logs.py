import logging
from aiogram import Router
from aiogram.types import Message, FSInputFile
from app.config import LOG_FILE

router = Router()
from aiogram.filters import Command

@router.message(Command("logs"))
async def cmd_logs(message: Message):
    try:
        await message.answer_document(FSInputFile(LOG_FILE), caption="Логи бота")
    except Exception:
        logging.exception("Не вдалось відправити лог-файл")
        await message.answer("Не вдалось відправити лог-файл. Перевірте наявність ./logs/bot.log")
