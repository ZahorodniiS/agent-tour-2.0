from __future__ import annotations
from typing import Any, Dict, Tuple, Optional, List
from datetime import datetime

CURRENCY_SIGN = {1: "$", 2: "₴", 10: "€"}

def _starize(hotel_rating: Optional[str]) -> str:
    if not hotel_rating:
        return "—"
    try:
        n = int(str(hotel_rating).strip()[0])
        n = max(1, min(5, n))
        return "★" * n
    except Exception:
        return "—"

def _fmt_date(api_date: Optional[str]) -> str:
    if not api_date:
        return "—"
    try:
        dt = datetime.strptime(api_date, "%Y-%m-%d")
        return dt.strftime("%d.%m.%Y")
    except Exception:
        return api_date

def _pick_price(prices: Dict[str, Any] | None, currency_id: int) -> Tuple[Optional[float], str]:
    if not prices or not isinstance(prices, dict):
        return None, ""
    direct = prices.get(currency_id) or prices.get(str(currency_id))
    if isinstance(direct, (int, float)):
        return float(direct), CURRENCY_SIGN.get(currency_id, "")
    for k, v in prices.items():
        try:
            val = float(v)
            k_int = int(k)
            return val, CURRENCY_SIGN.get(k_int, "")
        except Exception:
            continue
    return None, ""

def _short(text: Any, limit: int = 80) -> str:
    s = str(text or "").strip()
    return (s[:limit] + "…") if len(s) > limit else s

def build_offer_caption(o: Dict[str, Any], currency_id: int) -> Tuple[str, Optional[str]]:
    hotel = o.get("hotel") or o.get("name") or "Готель"
    stars = _starize(o.get("hotel_rating"))
    region = o.get("region") or "—"
    country = o.get("country") or "—"
    meal = o.get("meal_type_full") or o.get("meal_type") or "—"
    date_from = _fmt_date(o.get("date_from"))
    nights = o.get("duration") or o.get("hnight") or "—"
    from_city = o.get("from_city") or "—"
    prices = o.get("prices") or {}
    price_val, sign = _pick_price(prices, currency_id)
    price_str = f"{int(price_val):,}".replace(",", " ") + f" {sign}" if price_val is not None else "—"

    image_url = None
    imgs = o.get("hotel_images") or []
    if isinstance(imgs, list) and imgs:
        image_url = imgs[0].get("full") or imgs[0].get("thumb")

    caption = (
        f"<b>{_short(hotel, 60)}</b> {stars}\n"
        f"{_short(region, 40)}, {country}\n"
        f"🍽 {meal}\n"
        f"🛫 {from_city} • 📅 {date_from} • 🛌 {nights} ноч.\n"
        f"💰 {price_str}"
    )
    return caption, image_url

def offers_to_messages(data: Dict[str, Any], currency_id: int = 2) -> List[Tuple[str, Optional[str]]]:
    offers: List[Dict[str, Any]] = (data or {}).get("offers") or []
    res: List[Tuple[str, Optional[str]]] = []
    for o in offers[:10]:
        res.append(build_offer_caption(o, currency_id))
    return res
