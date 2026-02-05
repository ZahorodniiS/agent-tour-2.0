from __future__ import annotations
from typing import Any, Dict, Tuple, Optional, List, DefaultDict
from datetime import datetime
from collections import defaultdict

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


def _date_sort_key(api_date: Optional[str]) -> Tuple[int, Any]:
    if not api_date:
        return (1, "")
    try:
        return (0, datetime.strptime(api_date, "%Y-%m-%d"))
    except Exception:
        return (1, str(api_date))


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


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        if v is None:
            return default
        return int(v)
    except Exception:
        return default


def _fmt_people(adults: Any, children: Any) -> str:
    a = _safe_int(adults, 0)
    c = _safe_int(children, 0)
    parts = []
    if a:
        parts.append(f"{a} доросл." if a != 1 else "1 доросл.")
    if c:
        parts.append(f"{c} дит." if c != 1 else "1 дит.")
    return " • ".join(parts) if parts else ""


def _offer_key(o: Dict[str, Any]) -> Tuple:
    prices = o.get("prices") or {}
    return (
        str(o.get("date_from") or ""),
        str(o.get("duration") or o.get("hnight") or ""),
        f"{prices.get('1', '')}|{prices.get('2', '')}|{prices.get('10', '')}",
    )


def _hotel_group_key(o: Dict[str, Any]) -> Tuple:
    hid = o.get("hotel_id")
    if hid is not None:
        return ("hotel_id", str(hid))
    hotel = (o.get("hotel") or o.get("name") or "").strip().lower()
    region = (o.get("region") or "").strip().lower()
    country = (o.get("country") or "").strip().lower()
    stars = str(o.get("hotel_rating") or "")
    return ("fallback", hotel, region, country, stars)


def build_offer_caption(o: Dict[str, Any], currency_id: int, *, include_people: bool = True) -> Tuple[str, Optional[str]]:
    hotel = o.get("hotel") or o.get("name") or "Готель"
    stars = _starize(o.get("hotel_rating"))
    region = o.get("region") or "—"
    country = o.get("country") or "—"
    meal = o.get("meal_type_full") or o.get("meal_type") or "—"
    date_from = _fmt_date(o.get("date_from"))
    nights = o.get("duration") or o.get("hnight") or "—"
    from_city = o.get("from_city") or "—"

    people = ""
    if include_people:
        people = _fmt_people(o.get("adult_amount"), o.get("child_amount"))

    prices = o.get("prices") or {}
    price_val, sign = _pick_price(prices, currency_id)
    price_str = f"{int(price_val):,}".replace(",", " ") + f" {sign}" if price_val is not None else "—"

    image_url = None
    imgs = o.get("hotel_images") or []
    if isinstance(imgs, list) and imgs:
        image_url = imgs[0].get("full") or imgs[0].get("thumb")

    line_people = f"👥 {people}\n" if people else ""

    caption = (
        f"<b>{_short(hotel, 60)}</b> {stars}\n"
        f"{_short(region, 40)}, {country}\n"
        f"🍽 {meal}\n"
        f"{line_people}"
        f"🛫 {from_city} • 🗓️ {date_from} • 🛌 {nights} ноч.\n"
        f"💰 {price_str}"
    )
    return caption, image_url


def offers_to_messages(data: Dict[str, Any], currency_id: int = 2) -> List[Tuple[str, Optional[str]]]:
    offers: List[Dict[str, Any]] = (data or {}).get("offers") or []
    if not isinstance(offers, list) or not offers:
        return []

    grouped: DefaultDict[Tuple, List[Dict[str, Any]]] = defaultdict(list)
    for o in offers:
        if isinstance(o, dict):
            grouped[_hotel_group_key(o)].append(o)

    messages: List[Tuple[str, Optional[str]]] = []

    for group in grouped.values():
        # 1) прибираємо повні дублікати
        uniq: List[Dict[str, Any]] = []
        seen = set()
        for o in group:
            k = _offer_key(o)
            if k in seen:
                continue
            seen.add(k)
            uniq.append(o)

        if not uniq:
            continue

        # 2) схлопуємо лише (date_from + nights): залишаємо найнижчу ціну
        best_by_date_nights: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for o in uniq:
            d = str(o.get("date_from") or "")
            nights = str(o.get("duration") or o.get("hnight") or "")
            key = (d, nights)

            cur_best = best_by_date_nights.get(key)

            v_new, _ = _pick_price(o.get("prices") or {}, currency_id)
            v_best = None
            if cur_best is not None:
                v_best, _ = _pick_price(cur_best.get("prices") or {}, currency_id)

            new_num = v_new if v_new is not None else 10**18
            best_num = v_best if v_best is not None else 10**18

            if cur_best is None or new_num < best_num:
                best_by_date_nights[key] = o

        uniq2 = list(best_by_date_nights.values())
        if not uniq2:
            continue

        # 3) сортуємо: дата ↑, ночі ↑
        def nights_sort(o: Dict[str, Any]) -> int:
            try:
                return int(o.get("duration") or o.get("hnight") or 0)
            except Exception:
                return 0

        uniq2.sort(key=lambda o: (_date_sort_key(o.get("date_from")), nights_sort(o)))

        # 4) головний — найнижча ціна з усіх варіантів
        def price_num(o: Dict[str, Any]) -> float:
            v, _ = _pick_price(o.get("prices") or {}, currency_id)
            return v if v is not None else 10**18

        main = min(uniq2, key=price_num)
        others = [o for o in uniq2 if o is not main]

        main_caption, image_url = build_offer_caption(main, currency_id, include_people=True)

        # 5) обмеження: максимум 5 інших варіантів
        others = others[:5]

        if others:
            lines = [main_caption, ""]
            for o in others:
                date_from = _fmt_date(o.get("date_from"))
                nights = o.get("duration") or o.get("hnight") or "—"
                price_val, sign = _pick_price(o.get("prices") or {}, currency_id)
                price_str = f"{int(price_val):,}".replace(",", " ") + f" {sign}" if price_val is not None else "—"
                lines.append(f"• 🗓️ {date_from} • 🛌 {nights} ноч.")
                lines.append(f"💰 {price_str}")
            caption = "\n".join(lines).strip()
        else:
            caption = main_caption

        messages.append((caption, image_url))

    def msg_min_price_num(msg: Tuple[str, Optional[str]]) -> float:
        cap = msg[0]
        for line in cap.splitlines():
            if line.strip().startswith("💰"):
                digits = "".join(ch for ch in line if ch.isdigit())
                try:
                    return float(digits)
                except Exception:
                    return 10**18
        return 10**18

    messages.sort(key=msg_min_price_num)
    return messages[:10]
