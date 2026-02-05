import logging, json, os, re, difflib
from datetime import datetime, timedelta
from typing import Optional, Tuple

from aiogram import Router, F
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)
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

# ---------------------------
# Date normalization
# ---------------------------

_UA_MONTHS = {
    # родовий
    "січня": 1, "лютого": 2, "березня": 3, "квітня": 4, "травня": 5, "червня": 6,
    "липня": 7, "серпня": 8, "вересня": 9, "жовтня": 10, "листопада": 11, "грудня": 12,
    # називний
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
      - "25 квітня" / "25 квітня 2026" -> конвертація
    """
    if not date_str:
        raise ValueError("date_str is empty")

    now = now or datetime.now()
    s = str(date_str).strip().lower()
    s = re.sub(r"\s+", " ", s)

    # 1) "25 квітня" / "25 квітня 2026"
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
            yyyy = now.year
            candidate = datetime(yyyy, mm, dd)
            if candidate.date() < now.date():
                yyyy += 1

        return f"{dd:02d}.{mm:02d}.{yyyy % 100:02d}"

    # 2) unify separators
    s2 = s.replace(",", ".").replace("/", ".").replace("-", ".")
    s2 = re.sub(r"\s+", "", s2)

    # DD.MM
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})", s2)
    if m:
        dd = int(m.group(1))
        mm = int(m.group(2))
        yyyy = now.year
        candidate = datetime(yyyy, mm, dd)
        if candidate.date() < now.date():
            yyyy += 1
        return f"{dd:02d}.{mm:02d}.{yyyy % 100:02d}"

    # DD.MM.YY
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{2})", s2)
    if m:
        dd = int(m.group(1))
        mm = int(m.group(2))
        yy = int(m.group(3))
        return f"{dd:02d}.{mm:02d}.{yy:02d}"

    # DD.MM.YYYY
    m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", s2)
    if m:
        dd = int(m.group(1))
        mm = int(m.group(2))
        yyyy = int(m.group(3))
        return f"{dd:02d}.{mm:02d}.{yyyy % 100:02d}"

    raise ValueError(f"Unsupported date format: {date_str}")

# ---------------------------
# Fuzzy matching for country/city
# ---------------------------

def _norm_text(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^\wа-яіїєґ'\- ]+", " ", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def fuzzy_lookup(name: Optional[str], mapping: dict, cutoff: float = 0.78) -> Optional[int]:
    """
    Повертає ID з mapping по приблизній назві.
    mapping: {"Кишинів": 143, ...}
    """
    if not name:
        return None

    # пряме по ключу
    if name in mapping:
        return mapping[name]

    # нормалізоване порівняння
    keys = list(mapping.keys())
    norm_to_key = {_norm_text(k): k for k in keys}

    n = _norm_text(name)
    if n in norm_to_key:
        return mapping[norm_to_key[n]]

    # closest match
    candidates = difflib.get_close_matches(n, list(norm_to_key.keys()), n=1, cutoff=cutoff)
    if candidates:
        best_key = norm_to_key[candidates[0]]
        return mapping.get(best_key)

    return None

# ---------------------------
# UI helpers
# ---------------------------

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

def _set_draft(chat_id: int, **kwargs):
    """
    Зберігаємо 'чернетку' запиту: те, що вже зібрано, + прапорець що чекаємо місто
    """
    current = state_get(chat_id) or {}
    merged = {**current, **kwargs}
    state_set(chat_id, **merged)

def _pick(*vals, allow_zero: bool = False):
    for v in vals:
        if v is None:
            continue
        if v == "" or v == [] or v == {}:
            continue
        if v == 0 and not allow_zero:
            continue
        return v
    return None

async def _ask_missing(message: Message, state: dict) -> bool:
    """
    Повертає True якщо ми щось запитали (і зупинилися), і False якщо можна продовжувати.
    """
    if not state.get("country_id"):
        await message.answer("Куди летимо? 🌍 Напишіть країну (наприклад: Єгипет / Туреччина).")
        return True

    if not state.get("from_city_id"):
        # Важливо: тут НЕ пишемо "напишіть запит", бо він уже міг бути.
        await message.answer("Звідки виліт? ✈️ Оберіть місто:", reply_markup=city_keyboard())
        _set_draft(message.chat.id, awaiting_from_city=True)
        return True

    # adults must exist
    if state.get("adults") in (None, ""):
        await message.answer("Скільки дорослих? 👤 (наприклад: 2)")
        return True

    # children якщо нема — ставимо 0, не питаємо
    if state.get("children") in (None, ""):
        _set_draft(message.chat.id, children=0)

    # date_from якщо нема — запитаємо (або можеш поставити дефолт, але ти хотів уточнювати)
    if not state.get("date_from"):
        await message.answer("На яку дату виїзду? 🗓️ (10.12 / 25,4 / 25 квітня / 10.12.2026)")
        return True

    # budget (якщо взагалі нема) — запит
    if (state.get("budget_from") in (None, "")) and (state.get("budget_to") in (None, "")):
        await message.answer("Який бюджет? 💰 (наприклад: 1500$ або 70000 грн)")
        return True

    return False

async def _run_search(message: Message, state: dict):
    now = datetime.now()

    # нормалізація дат
    date_from = state.get("date_from")
    date_till = state.get("date_till")

    if date_from:
        try:
            date_from = normalize_date_ddmmyy(date_from, now=now)
        except Exception:
            await message.answer("Не можу розпізнати дату 🗓️ Напишіть: 10.12 / 25,4 / 25 квітня / 10.12.2026")
            return

    if date_till:
        try:
            date_till = normalize_date_ddmmyy(date_till, now=now)
        except Exception:
            await message.answer("Не можу розпізнати дату 'до' 🗓️ Напишіть: 10.12 / 25,4 / 25 квітня / 10.12.2026")
            return

    # дефолти дат якщо date_till нема (але date_from є)
    if not date_from:
        date_from = (now + timedelta(days=2)).strftime("%d.%m.%y")
    if not date_till:
        df = datetime.strptime(date_from, "%d.%m.%y")
        date_till = (df + timedelta(days=12)).strftime("%d.%m.%y")

    # гарантуємо числа
    adults = state.get("adults")
    children = state.get("children")

    adults_i = int(adults) if adults not in (None, "") else int(DEFAULTS.get("adult_amount", 2))

    # важливо: 0 дітей — валідно
    children_i = int(children) if children not in (None, "") else int(DEFAULTS.get("child_amount", 0))

    # збережемо нормалізовані дати назад у state
    _set_draft(message.chat.id, date_from=date_from, date_till=date_till, adults=adults_i, children=children_i, awaiting_from_city=False)

    try:
        url, params = build_search_list_query(
            country_id=state.get("country_id"),
            from_city_id=state.get("from_city_id"),
            adults=adults_i,
            children=children_i,
            child_ages=state.get("child_ages"),
            night_from=DEFAULTS["night_from"],
            night_till=DEFAULTS["night_till"],
            hotel_rating=DEFAULTS["hotel_rating"],
            date_from_str=date_from,
            date_till_str=date_till,
            kind=DEFAULTS["kind"],
            tour_type=DEFAULTS["type"],
            currency_hint=state.get("currency_hint"),
            budget_to=state.get("budget_to"),
            budget_from=state.get("budget_from"),
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
        # Дружніше перепитування
        if missing == "from_city":
            await message.answer("Потрібне місто вильоту ✈️ Оберіть зі списку:", reply_markup=city_keyboard())
            _set_draft(message.chat.id, awaiting_from_city=True)
            return
        if missing == "country":
            await message.answer("Потрібна країна 🌍 Напишіть країну (наприклад: Єгипет).")
            return
        await message.answer(f"Поле {missing} є обов'язковим. Будь ласка, доповніть дані.")
        return

    try:
        data = request_search_list(params)
    except Exception:
        await message.answer("Сервіс тимчасово недоступний. Спробуйте пізніше.")
        return

   if isinstance(data, dict) and ("error_code" in data or "error" in data or "code" in data):
    code = data.get("error_code") or data.get("code")
    if not code and isinstance(data.get("error"), dict):
        code = data["error"].get("error_code") or data["error"].get("code")
    try:
        code_int = int(code)
    except Exception:
        code_int = 0

    tip = humanize_error(code_int, data)
    await message.answer(f"Сталася помилка ITTour ({code_int}). {tip}")
    return

# якщо прийшла строка (HTML/текст), щоб не падати
    if not isinstance(data, dict):
    await message.answer("Помилка ITTour: відповідь не у форматі JSON. Перевіряю доступ/токен.")
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

# ---------------------------
# Handlers
# ---------------------------

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

@router.callback_query(F.data == "search_start")
async def cb_search_start(cb: CallbackQuery):
    # початок діалогу — просимо місто вильоту, але НЕ вимагаємо новий “повний запит”
    _set_draft(cb.message.chat.id, awaiting_from_city=True)
    await cb.message.answer("Почнемо 🙂 Звідки виліт? ✈️ Оберіть місто:", reply_markup=city_keyboard())
    await cb.answer()

@router.callback_query(F.data.startswith("from_city:"))
async def cb_from_city(cb: CallbackQuery):
    try:
        fid = int(cb.data.split(":", 1)[1])
    except Exception:
        await cb.answer("Некоректні дані міста", show_alert=True)
        return

    # ВАЖЛИВО: ми НЕ просимо заново запит, а продовжуємо з чернеткою
    st = state_get(cb.message.chat.id) or {}
    _set_draft(cb.message.chat.id, from_city_id=fid, awaiting_from_city=False)

    await cb.message.answer("Дякую! ✅ Зберіг місто вильоту. Перевіряю ваш запит…")
    await cb.answer()

    # Тепер продовжуємо: якщо чогось не вистачає — запитаємо; інакше пошук
    st2 = state_get(cb.message.chat.id) or {}
    asked = await _ask_missing(cb.message, st2)
    if asked:
        return
    await _run_search(cb.message, st2)

@router.message()
async def handle_text(message: Message):
    user_text = (message.text or "").strip()
    cached = state_get(message.chat.id) or {}

    with open(os.path.join(DATA_DIR, "country_map.json"), "r", encoding="utf-8") as f:
        COUNTRY_MAP = json.load(f)
    with open(os.path.join(DATA_DIR, "from_city_map.json"), "r", encoding="utf-8") as f:
        CITY_MAP = json.load(f)

    # 1) Витягаємо структуру (LLM + rule-based)
    llm = llm_extract(user_text, COUNTRY_MAP, CITY_MAP)
    rb = parse_user_text(user_text)

    # 2) Fuzzy підбір якщо назва є, а id не вийшов
    # country
    country_id = _pick(
        llm.get("country_id"),
        rb.get("country_id"),
        fuzzy_lookup(llm.get("country_name"), COUNTRY_MAP),
        fuzzy_lookup(rb.get("country_name"), COUNTRY_MAP),
        cached.get("country_id"),
    )

    # from_city
    from_city_id = _pick(
        llm.get("from_city_id"),
        rb.get("from_city_id"),
        fuzzy_lookup(llm.get("from_city_name"), CITY_MAP),
        fuzzy_lookup(rb.get("from_city_name"), CITY_MAP),
        cached.get("from_city_id"),
    )

    adults = _pick(llm.get("adults"), rb.get("adults"), cached.get("adults"), DEFAULTS.get("adult_amount", 2))
    children = _pick(llm.get("children"), rb.get("children"), cached.get("children"), DEFAULTS.get("child_amount", 0), allow_zero=True)

    child_ages = _pick(llm.get("child_ages"), rb.get("child_ages"), cached.get("child_ages"))

    date_from = _pick(llm.get("date_from"), rb.get("date_from"), cached.get("date_from"))
    date_till = _pick(llm.get("date_till"), rb.get("date_till"), cached.get("date_till"))

    currency_hint = _pick(llm.get("currency_hint"), rb.get("currency_hint"), cached.get("currency_hint"))
    budget_from = _pick(llm.get("budget_from"), rb.get("budget_from"), cached.get("budget_from"), DEFAULTS.get("price_from"))
    budget_to = _pick(llm.get("budget_to"), rb.get("budget_to"), cached.get("budget_to"), DEFAULTS.get("price_till"))

    # 3) Нормалізація дат одразу (якщо користувач їх написав)
    now = datetime.now()
    if date_from:
        try:
            date_from = normalize_date_ddmmyy(date_from, now=now)
        except Exception:
            await message.answer("Не можу розпізнати дату 🗓️ Напишіть: 10.12 / 25,4 / 25 квітня / 10.12.2026")
            return

    if date_till:
        try:
            date_till = normalize_date_ddmmyy(date_till, now=now)
        except Exception:
            await message.answer("Не можу розпізнати дату 'до' 🗓️ Напишіть: 10.12 / 25,4 / 25 квітня / 10.12.2026")
            return

    # 4) Зберігаємо чернетку (це і є ключ, щоб після вибору міста не просити запит заново)
    _set_draft(
        message.chat.id,
        country_id=country_id,
        from_city_id=from_city_id,
        adults=adults,
        children=children,
        child_ages=child_ages,
        date_from=date_from,
        date_till=date_till,
        currency_hint=currency_hint,
        budget_from=budget_from,
        budget_to=budget_to,
        last_user_text=user_text,  # інколи корисно для дебагу
    )

    st = state_get(message.chat.id) or {}

    # 5) Якщо чогось бракує — уточнюємо тільки це
    asked = await _ask_missing(message, st)
    if asked:
        return

    # 6) Інакше запускаємо пошук
    await _run_search(message, st)
