import logging, json, os, re
from datetime import datetime, timedelta

from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.filters import CommandStart

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

_UA_MONTHS = {
    # родовий (найчастіше у фразах "25 квітня")
    "січня": 1, "лютого": 2, "березня": 3, "квітня": 4, "травня": 5, "червня": 6,
    "липня": 7, "серпня": 8, "вересня": 9, "жовтня": 10, "листопада": 11, "грудня": 12,
    # називний (про всяк випадок)
    "січень": 1, "лютий": 2, "березень": 3, "квітень": 4, "травень": 5, "червень": 6,
    "липень": 7, "серпень": 8, "вересень": 9, "жовтень": 10, "листопад": 11, "грудень": 12,
}

def normalize_date_ddmmyy(date_str: str, now: datetime | None = None) -> str:
    """
    Приводить дату до формату DD.MM.YY

    Підтримує:
      - "25.04" / "25.4" -> додає рік (поточний або наступний, щоб не було в минулому)
      - "25,04" / "25,4" -> те саме
      - "25/04", "25-04" -> те саме
      - "25.04.26" -> ok
      - "25.04.2026" -> "25.04.26"
      - "25 квітня" / "25 квітня 2026" -> конвертація в DD.MM.YY
    """
    if not date_str:
        raise ValueError("date_str is empty")

    now = now or datetime.now()

    s = str(date_str).strip().lower()
    s = re.sub(r"\s+", " ", s)

    # 1) Спроба розпізнати "25 квітня" або "25 квітня 2026"
    m = re.fullmatch(r"(\d{1,2})\s+([а-яіїєґ]+)(?:\s+(\d{2,4}))?", s)
    if m:
        dd = int(m.group(1))
        month_name = m.group(2)
        mm = _UA_MONTHS.get(month_name)
        if not mm:
            raise ValueError(f"Unknown month name: {month_name}")

        y_raw = m.group(3)
        if y_raw:
            yyyy = int(y_raw)
            if yyyy < 100:
                yyyy = 2000 + yyyy
        else:
            # Якщо рік не вказаний — беремо поточний або наступний, щоб дата була не в минулому
            yyyy = now.year
            candidate = datetime(yyyy, mm, dd)
            if candidate.date() < now.date():
                yyyy += 1

        yy = yyyy % 100
        return f"{dd:02d}.{mm:02d}.{yy:02d}"

    # 2) Нормалізація роздільників: кома/слеш/дефіс -> крапка
    s2 = s.replace(",", ".").replace("/", ".").replace("-", ".")
    s2 = re.sub(r"\s+", "", s2)

    # 2.1) DD.MM
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})", s2)
    if m:
        dd = int(m.group(1))
        mm = int(m.group(2))
        yyyy = now.year
        candidate = datetime(yyyy, mm, dd)
        if candidate.date() < now.date():
            yyyy += 1
        yy = yyyy % 100
        return f"{dd:02d}.{mm:02d}.{yy:02d}"

    # 2.2) DD.MM.YY
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{2})", s2)
    if m:
        dd = int(m.group(1))
        mm = int(m.group(2))
        yy = int(m.group(3))
        return f"{dd:02d}.{mm:02d}.{yy:02d}"

    # 2.3) DD.MM.YYYY
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", s2)
    if m:
        dd = int(m.group(1))
        mm = int(m.group(2))
        yyyy = int(m.group(3))
        yy = yyyy % 100
        return f"{dd:02d}.{mm:02d}.{yy:02d}"

    raise ValueError(f"Unsupported date format: {date_str}")

def city_keyboard() -> InlineKeyboardMarkup:
    with open(os.path.join(DATA_DIR, "from_city_map.json"), "r", encoding="utf-8") as f:
        city_map = json.load(f)

    btns = []
    top = ["Кишинів", "Варшава", "Краків", "Ясси"]

    for name in top:
        fid = city_map.get(name)
        if fid:
            btns.append([InlineKeyboardButton(text=name, callback_data=f"from_city:{fid}")])

    return InlineKeyboardMarkup(inline_keyboard=btns)

@router.message(CommandStart())
async def start(message: Message):
    example = (
        "Вітаю, я ваш віртуальний турагент!\n"
        "Натисніть кнопку нижче або надішліть запит у довільній формі.\n\n"
        "Приклад: <i>Тур до Єгипту на 2 дорослих, з 10.12.2026, бюджет 1500 дол на 7 днів</i>"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Здійснити пошук туру", callback_data="search_start")]]
    )
    await message.answer(example, reply_markup=kb)

# ✅ ОБРОБНИК КНОПКИ "Здійснити пошук туру"
@router.callback_query(F.data == "search_start")
async def on_search_start(callback: CallbackQuery):
    await callback.answer()  # прибирає "годинник" на кнопці
    await callback.message.answer(
        "Оберіть місто вильоту або введіть вручну:",
        reply_markup=city_keyboard()
    )

# ✅ ОБРОБНИК ВИБОРУ МІСТА ВИЛЬОТУ
@router.callback_query(F.data.startswith("from_city:"))
async def on_from_city(callback: CallbackQuery):
    await callback.answer()
    fid = callback.data.split(":", 1)[1]
    state_set(callback.message.chat.id, from_city_id=fid)
    await callback.message.answer(
        "✅ Місто вильоту збережено.\nТепер напишіть запит одним повідомленням 🙂\n\n"
        "Наприклад: <i>Тур до Єгипту на 2 дорослих, з 10.12.2026, бюджет 1500 дол на 7 днів</i>"
    )

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

    def pick(*vals, allow_zero: bool = False):
    for v in vals:
        if v is None:
            continue
        if v == "" or v == [] or v == {}:
            continue
        if (v == 0) and (not allow_zero):
            continue
        return v
    return None

    country_id   = pick(llm.get("country_id"), rb.get("country_id"), COUNTRY_MAP.get(llm.get("country_name","")), COUNTRY_MAP.get(rb.get("country_name","")), cached.get("country_id"))
    from_city_id = pick(llm.get("from_city_id"), rb.get("from_city_id"), CITY_MAP.get(llm.get("from_city_name","")), CITY_MAP.get(rb.get("from_city_name","")), cached.get("from_city_id"))
    adults   = pick(llm.get("adults"), rb.get("adults"), cached.get("adults"), DEFAULTS.get("adult_amount", 2), allow_zero=False)
    children = pick(llm.get("children"), rb.get("children"), cached.get("children"), DEFAULTS.get("child_amount", 0), allow_zero=True)
    child_ages   = pick(llm.get("child_ages"), rb.get("child_ages"), cached.get("child_ages"))
    date_from    = pick(llm.get("date_from"), rb.get("date_from"), cached.get("date_from"))
    date_till    = pick(llm.get("date_till"), rb.get("date_till"), cached.get("date_till"))
    currency_hint= pick(llm.get("currency_hint"), rb.get("currency_hint"), cached.get("currency_hint"))
    budget_from  = pick(llm.get("budget_from"), rb.get("budget_from"), cached.get("budget_from"), DEFAULTS["price_from"])
    budget_to    = pick(llm.get("budget_to"), rb.get("budget_to"), cached.get("budget_to"), DEFAULTS["price_till"])

    # ✅ НОРМАЛІЗУЄМО ДАТИ (якщо вони прийшли)
    now = datetime.now()
    if date_from:
        try:
            date_from = normalize_date_ddmmyy(date_from, now=now)
        except Exception:
            await message.answer("Не можу розпізнати дату 🗓️ Напишіть, будь ласка, у форматі 25.04 / 25,04 / 25 квітня / 25.04.26")
            return
    if date_till:
        try:
            date_till = normalize_date_ddmmyy(date_till, now=now)
        except Exception:
            await message.answer("Не можу розпізнати дату 'до' 🗓️ Напишіть, будь ласка, у форматі 25.04 / 25,04 / 25 квітня / 25.04.26")
            return

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

    today = now
    if not date_from:
        date_from = (today + timedelta(days=2)).strftime('%d.%m.%y')
    if not date_till:
        # date_from тут вже гарантовано у форматі DD.MM.YY
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
