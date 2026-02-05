from datetime import datetime, timedelta
from urllib.parse import urlencode
import logging
import requests
from typing import Optional, Tuple, Dict, Any

from app.config import ITTOUR_API_TOKEN, ACCEPT_LANGUAGE


CURRENCY_MAP = {
    "uah": 2,
    "грн": 2,
    "гривня": 2,
    "гривні": 2,
    "usd": 1,
    "дол": 1,
    "долар": 1,
    "долари": 1,
    "доларів": 1,
    "$": 1,
    "eur": 10,
    "євро": 10,
    "€": 10,
}


def fmt_dmy(d: datetime) -> str:
    return d.strftime("%d.%m.%y")


def _normalize_ittour_response(data: Any) -> Dict[str, Any]:
    """
    ITTour інколи повертає:
      - dict (норма)
      - list з 1 dict (помилки бувають так)
      - string (інколи при 401/проксі/edge cases)

    Приводимо все до dict.
    """
    if isinstance(data, dict):
        return data

    if isinstance(data, list):
        # Частий кейс: [{"error": "...", "error_desc": "...", "error_code": 100}]
        if len(data) == 1 and isinstance(data[0], dict):
            return data[0]
        return {
            "error": "Invalid response format",
            "error_desc": "List response",
            "error_code": 110,
            "raw": data,
        }

    if isinstance(data, str):
        return {
            "error": "Invalid response format",
            "error_desc": data[:500],
            "error_code": 110,
            "raw": data,
        }

    return {
        "error": "Invalid response format",
        "error_desc": str(type(data)),
        "error_code": 110,
        "raw": repr(data)[:1000],
    }


def _ensure_error_shape(data: Dict[str, Any], *, http_status: int | None = None) -> Dict[str, Any]:
    """
    Гарантуємо, що при помилці є:
      - error
      - error_desc
      - error_code (int, якщо можливо)
    """
    # якщо вже ок — повертаємо як є
    if "error" not in data and "error_code" not in data and "code" not in data:
        return data

    # зчитуємо error_code з різних полів
    code = data.get("error_code", None)
    if code is None:
        code = data.get("code", None)
    if code is None and isinstance(data.get("error"), dict):
        code = data["error"].get("code")

    try:
        code_int = int(code) if code is not None else None
    except Exception:
        code_int = None

    # error може бути dict — приводимо до рядка
    err = data.get("error")
    if isinstance(err, dict):
        err = err.get("message") or err.get("title") or str(err)

    desc = data.get("error_desc")
    if desc is None and isinstance(data.get("error"), dict):
        desc = data["error"].get("message")

    # якщо ITTour повернув 401/403/… без коду — підставимо 110 "Unknown error"
    if code_int is None and http_status and http_status != 200:
        code_int = 110

    # формуємо єдиний формат
    out = dict(data)
    out["error"] = err or "API error"
    out["error_desc"] = desc or ""
    if code_int is not None:
        out["error_code"] = code_int
    return out


def build_search_list_query(
    *,
    country_id: int,
    from_city_id: Optional[int],
    adults: Optional[int],
    children: Optional[int],
    child_ages: Optional[str],
    night_from: Optional[int],
    night_till: Optional[int],
    hotel_rating: Optional[str | int],
    date_from_str: Optional[str],
    date_till_str: Optional[str],
    kind: Optional[int],
    tour_type: Optional[int],
    currency_hint: Optional[str],
    budget_to: Optional[int],
    budget_from: Optional[int],
    items_per_page: Optional[int],
    today: Optional[datetime] = None,
) -> Tuple[str, Dict[str, Any]]:

    if today is None:
        today = datetime.now()

    tour_type = tour_type or 1
    kind = kind or 1
    hotel_rating = str(hotel_rating or 78)
    adults = adults or 2
    children = children or 0
    night_from = night_from or 6
    night_till = night_till or 8
    items_per_page = items_per_page or 10

    if date_from_str:
        date_from = datetime.strptime(date_from_str, "%d.%m.%y")
    else:
        date_from = today + timedelta(days=2)

    if date_till_str:
        date_till = datetime.strptime(date_till_str, "%d.%m.%y")
    else:
        date_till = date_from + timedelta(days=12)

    if (date_till - date_from).days > 12:
        date_till = date_from + timedelta(days=12)

    if not (1 <= night_from <= 30 and 1 <= night_till <= 30 and night_from <= night_till):
        raise ValueError("Некоректні значення night_from/night_till (1..30, from ≤ till)")

    if not (1 <= adults <= 4):
        raise ValueError("adult_amount має бути 1..4")

    currency_id = 2
    if currency_hint:
        key = currency_hint.strip().lower()
        currency_id = CURRENCY_MAP.get(key, currency_id)

    params: Dict[str, Any] = {
        "type": tour_type,
        "kind": kind,
        "country": country_id,
        "hotel_rating": str(hotel_rating),
        "adult_amount": adults,
        "child_amount": children,
        "night_from": night_from,
        "night_till": night_till,
        "date_from": fmt_dmy(date_from),
        "date_till": fmt_dmy(date_till),
        "currency": currency_id,
        "items_per_page": items_per_page,
        "hotel_info": 1,
    }

    if from_city_id is not None:
        params["from_city"] = from_city_id

    if children > 0:
        if not child_ages:
            raise ValueError("child_age обов'язковий, якщо child_amount > 0 (напр. '7:4:3')")
        params["child_age"] = child_ages

    if budget_from is not None:
        params["price_from"] = int(budget_from)

    if budget_to is not None:
        params["price_till"] = int(budget_to)

    base = "https://api.ittour.com.ua/module/search-list"
    url = f"{base}?{urlencode(params)}"
    return url, params


def request_search_list(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Завжди повертає dict.
    Якщо ITTour повернув помилку — dict гарантовано має:
      error, error_desc, error_code
    """
    headers = {
        "Authorization": f"Bearer {ITTOUR_API_TOKEN}",
        "Accept-Language": ACCEPT_LANGUAGE,
    }

    resp = requests.get(
        "https://api.ittour.com.ua/module/search-list",
        params=params,
        headers=headers,
        timeout=25,
    )

    try:
        data_raw = resp.json()
    except Exception:
        logging.exception("ITTour: invalid JSON response")
        return {
            "error": "Invalid JSON",
            "error_desc": f"HTTP {resp.status_code}, cannot decode JSON",
            "error_code": 110,
            "raw": (resp.text or "")[:1000],
        }

    data = _normalize_ittour_response(data_raw)
    data = _ensure_error_shape(data, http_status=resp.status_code)

    if resp.status_code != 200:
        logging.error("ITTour: HTTP %s body=%s", resp.status_code, data)

    # якщо є помилка — лог з кодом (щоб легко шукати по журналу)
    if isinstance(data, dict) and ("error" in data or "error_code" in data):
        code = data.get("error_code")
        logging.error(
            "ITTour API error_code=%s error=%s desc=%s",
            code,
            data.get("error"),
            data.get("error_desc"),
        )

    return data
