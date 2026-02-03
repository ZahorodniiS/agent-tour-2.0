import re
from datetime import datetime

USD_HINTS = ("usd", "дол", "долар", "долари", "$")
EUR_HINTS = ("eur", "євро", "€")

def parse_user_text(text: str) -> dict:
    t = (text or "").lower()
    out = {
        "country_name": None,
        "from_city_name": None,
        "country_id": None,
        "from_city_id": None,
        "adults": None,
        "children": 0,
        "child_ages": None,
        "date_from": None,
        "date_till": None,
        "currency_hint": None,
        "budget_from": None,
        "budget_to": None,
    }

    m_city = re.search(r"(?:з|із)\s+([\w'’\-\s]+)", t)
    if m_city:
        out["from_city_name"] = m_city.group(1).strip()

    m_ad = re.search(r"(?:на|для)\s*(\d{1,2})", t)
    if m_ad:
        out["adults"] = int(m_ad.group(1))

    rng = re.search(r"від\s*(\d+)\s*до\s*(\d+)", t)
    if rng:
        out["budget_from"] = int(rng.group(1))
        out["budget_to"] = int(rng.group(2))
    else:
        up = re.search(r"до\s*(\d+)", t)
        if up:
            out["budget_from"] = 0
            out["budget_to"] = int(up.group(1))
        approx = re.search(r"близько\s*(\d+)", t)
        if approx and not out["budget_to"]:
            v = int(approx.group(1))
            out["budget_from"], out["budget_to"] = max(0, v - 200), v + 200

    if any(h in t for h in USD_HINTS):
        out["currency_hint"] = "usd"
    elif any(h in t for h in EUR_HINTS):
        out["currency_hint"] = "eur"

    m = re.search(r"(\d{1,2})[.](\d{1,2})(?:[.](\d{2}))?", t)
    if m:
        d, mth, yy = int(m.group(1)), int(m.group(2)), m.group(3)
        if yy is None:
            yy = int(datetime.now().strftime('%y'))
        else:
            yy = int(yy)
        out["date_from"] = f"{d:02d}.{mth:02d}.{yy:02d}"

    return out
