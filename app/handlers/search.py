import logging, json, os
from datetime import datetime, timedelta
from aiogram import Router
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from app import config
from app.config import DEFAULTS, DATA_DIR
from app.state import get as state_get, set as state_set
from app.services.ittour import build_search_list_query, request_search_list
from app.validators import validate_required
from app.render.cards import offers_to_messages
from app.nlp.parse import parse_user_text
from app.nlp.llm import llm_extract
from app.errors import humanize_error

router = Router()

def city_keyboard() -> InlineKeyboardMarkup:
    with open(os.path.join(DATA_DIR, "from_city_map.json"), "r", encoding="utf-8") as f:
        city_map = json.load(f)
    btns = []
    top = ["Київ", "Львів", "Варшава", "Кишинів", "Одеса"]
    for name in top:
        fid = city_map.get(name)
        if fid:
            btns.append([InlineKeyboardButton(text=name, callback_data=f"from_city:{fid}")])
    return InlineKeyboardMarkup(inline_keyboard=btns)

from aiogram.filters import CommandStart

@router.message(CommandStart())
async def start(message: Message):
    example = (
        "Вітаю, я ваш віртуальний турагент!\n"
        "Натисніть кнопку нижче або надішліть запит у довільній формі.\n\n"
        "Приклад: <i>Тур до Єгипту на 2 дорослих, з 10.12.2025, бюджет 1500 дол на 7 днів</i>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Здійснити пошук туру", callback_data="search_start")]])
    await message.answer(example, reply_markup=kb)

@router.message()
async def handle_text(message: Message):
    user_text = message.text or ""
    cached = state_get(message.chat.id)

    with open(os.path.join(DATA_DIR, "country_map.json"), "r", encoding="utf-8") as f:
        COUNTRY_MAP = json.load(f)
    with open(os.path.join(DATA_DIR, "from_city_map.json"), "r", encoding="utf-8") as f:
        CITY_MAP = json.load(f)

    llm = llm_extract(user_text, COUNTRY_MAP, CITY_MAP)
    rb = parse_user_text(user_text)

    def pick(*vals):
        for v in vals:
            if v not in (None, "", 0):
                return v
        return None

    country_id   = pick(llm.get("country_id"), rb.get("country_id"), COUNTRY_MAP.get(llm.get("country_name","")), COUNTRY_MAP.get(rb.get("country_name","")), cached.get("country_id"))
    from_city_id = pick(llm.get("from_city_id"), rb.get("from_city_id"), CITY_MAP.get(llm.get("from_city_name","")), CITY_MAP.get(rb.get("from_city_name","")), cached.get("from_city_id"))
    adults       = pick(llm.get("adults"), rb.get("adults"), cached.get("adults"), DEFAULTS["adult_amount"])
    children     = pick(llm.get("children"), rb.get("children"), cached.get("children"), DEFAULTS["child_amount"])
    child_ages   = pick(llm.get("child_ages"), rb.get("child_ages"), cached.get("child_ages"))
    date_from    = pick(llm.get("date_from"), rb.get("date_from"), cached.get("date_from"))
    date_till    = pick(llm.get("date_till"), rb.get("date_till"), cached.get("date_till"))
    currency_hint= pick(llm.get("currency_hint"), rb.get("currency_hint"), cached.get("currency_hint"))
    budget_from  = pick(llm.get("budget_from"), rb.get("budget_from"), cached.get("budget_from"), DEFAULTS["price_from"])
    budget_to    = pick(llm.get("budget_to"), rb.get("budget_to"), cached.get("budget_to"), DEFAULTS["price_till"])

    state_set(message.chat.id,
              country_id=country_id, from_city_id=from_city_id, adults=adults, children=children,
              child_ages=child_ages, date_from=date_from, date_till=date_till, currency_hint=currency_hint,
              budget_from=budget_from, budget_to=budget_to)

    if not country_id:
        await message.answer("Нам не вистачає інформації по країні подорожі. 😔 Будь ласка, перевірте правильність написання та спробуйте ще раз.")
        return
    if not from_city_id:
        await message.answer("Звідки виліт? Оберіть місто нижче або введіть вручну:", reply_markup=city_keyboard())
        return

    today = datetime.now()
    if not date_from:
        date_from = (today + timedelta(days=2)).strftime('%d.%m.%y')
    if not date_till:
        df = datetime.strptime(date_from, '%d.%m.%y')
        date_till = (df + timedelta(days=12)).strftime('%d.%m.%y')

    try:
        url, params = build_search_list_query(
            country_id=country_id,
            from_city_id=from_city_id,
            adults=int(adults),
            children=int(children),
            child_ages=child_ages,
            night_from=DEFAULTS["night_from"],
            night_till=DEFAULTS["night_till"],
            hotel_rating=DEFAULTS["hotel_rating"],
            date_from_str=date_from,
            date_till_str=date_till,
            kind=DEFAULTS["kind"],
            tour_type=DEFAULTS["type"],
            currency_hint=currency_hint,
            budget_to=budget_to,
            budget_from=budget_from,
            items_per_page=DEFAULTS["items_per_page"],
        )
    except Exception as e:
        logging.exception("Помилка формування параметрів")
        await message.answer(f"Помилка параметрів: {e}")
        return

    missing = validate_required({
        "country": params.get("country"),
        "from_city": params.get("from_city"),
        "hotel_rating": params.get("hotel_rating"),
        "adult_amount": params.get("adult_amount"),
        "night_from": params.get("night_from"),
        "night_till": params.get("night_till"),
        "date_from": params.get("date_from"),
        "date_till": params.get("date_till"),
    })
    if missing:
        await message.answer(f"Поле {missing} є обов'язковим. Будь ласка, доповніть дані.")
        return

    try:
        data = request_search_list(params)
    except Exception:
        await message.answer("Сервіс тимчасово недоступний. Спробуйте пізніше.")
        return

    if isinstance(data, dict) and "error" in data:
        code = data.get("code") or data.get("error", {}).get("code")
        try:
            code = int(code)
        except Exception:
            code = None
        tip = humanize_error(code or 0)
        await message.answer(f"Сталася помилка API ({code}). {tip}")
        return

    currency_id = int(params.get("currency", config.CURRENCY_DEFAULT))
    offers = offers_to_messages(data, currency_id=currency_id)
    if not offers:
        await message.answer("За вашими умовами нічого не знайшлося. Спробуємо змінити бюджет/дати/ночі?")
        return

    for caption, image_url in offers:
        if image_url:
            try:
                await message.answer_photo(photo=image_url, caption=caption)
                continue
            except Exception:
                pass
        await message.answer(caption)

    if isinstance(data, dict) and data.get("has_more_pages"):
        page = data.get("page", 1)
        await message.answer(f"Показано {min(10, len(offers))} результатів (стор. {page}). Є ще результати. Надіслати наступну сторінку?")
