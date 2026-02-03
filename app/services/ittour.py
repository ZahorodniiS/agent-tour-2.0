from datetime import datetime, timedelta
from urllib.parse import urlencode
import logging
import requests
from typing import Optional, Tuple, Dict, Any

from app.config import ITTOUR_API_TOKEN, ACCEPT_LANGUAGE

CURRENCY_MAP = {
    'uah': 2, 'грн': 2, 'гривня': 2, 'гривні': 2,
    'usd': 1, 'дол': 1, 'долар': 1, 'долари': 1, 'доларів': 1, '$': 1,
    'eur': 10, 'євро': 10, '€': 10,
}

def fmt_dmy(d: datetime) -> str:
    return d.strftime('%d.%m.%y')

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
        date_from = datetime.strptime(date_from_str, '%d.%m.%y')
    else:
        date_from = today + timedelta(days=2)

    if date_till_str:
        date_till = datetime.strptime(date_till_str, '%d.%m.%y')
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
    headers = {
        "Authorization": f"Bearer {ITTOUR_API_TOKEN}",
        "Accept-Language": ACCEPT_LANGUAGE,
    }
    resp = requests.get("https://api.ittour.com.ua/module/search-list", params=params, headers=headers, timeout=25)
    try:
        data = resp.json()
    except Exception:
        logging.exception("ITTour: invalid JSON response")
        raise

    if resp.status_code != 200:
        logging.error("ITTour: HTTP %s body=%s", resp.status_code, data)
    if isinstance(data, dict) and "error" in data:
        logging.error("ITTour API error: %s", data)
    return data
