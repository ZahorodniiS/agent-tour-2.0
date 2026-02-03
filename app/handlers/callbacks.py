from aiogram import Router, F
from aiogram.types import CallbackQuery
from app.state import set as state_set

router = Router()

@router.callback_query(F.data.startswith("from_city:"))
async def choose_city(cb: CallbackQuery):
    try:
        _, fid = cb.data.split(":", 1)
        fid = int(fid)
    except Exception:
        await cb.answer("Помилка міста")
        return

    state_set(cb.message.chat.id, from_city_id=fid)
    await cb.message.answer("Дякую! Зберіг ваше місто вильоту. Тепер напишіть запит (країна/дати/бюджет).")
    await cb.answer()
