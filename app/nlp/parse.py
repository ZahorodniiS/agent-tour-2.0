import re
from datetime import datetime

USD_HINTS = ("usd", "дол", "долар", "долари", "$")
EUR_HINTS = ("eur", "євро", "€")

# ключові слова для дорослих/людей (щоб "на 25.06" не стало adults=25)
ADULT_WORDS = r"(доросл|людин|осіб|чол|персон|people|adults?)"

def parse_user_text(text: str) -> dict:
    t = (text or "").lower()

    out = {
        "country_name": None,
        "from_city_name": None,
        "country_id": None,
        "from_city_id": None,
        "adults": None,
        "children": None,          # ⚠️ важливо: None, щоб ми могли питати/ставити default
        "child_ages": None,
        "date_from": None,
        "date_till": None,
        "currency_hint": None,
        "budget_from": None,
        "budget_to": None,
    }

    # місто вильоту: "з варшави", "із кишинева"
    m_city = re.search(r"(?:з|із)\s+([\w'’\-\s]+)", t)
    if m_city:
        out["from_city_name"] = m_city.group(1).strip()

    # дорослі: тільки якщо є ключове слово
    # "2 дорослих", "на 2 людини", "для 3 осіб"
    m_ad = re.search(rf"(\d{{1,2}})\s*{ADULT_WORDS}\b", t)
    if not m_ad:
        m_ad = re.search(rf"(?:на|для)\s*(\d{{1,2}})\s*{ADULT_WORDS}\b", t)
    if m_ad:
        try:
            out["adults"] = int(m_ad.group(1))
        except Exception:
            pass

    # діти (опційно)
    m_ch = re.search(r"(\d{1,2})\s*(?:дит|діт)", t)
    if m_ch:
        try:
            out["children"] = int(m_ch.group(1))
        except Exception:
            pass

    # бюджет: "від 50000 до 80000", "до 70000", "близько 1500"
    rng = re.search(r"від\s*(\d+)\s*до\s*(\d+)", t)
    if rng:
        out["budget_from"] = int(rng.group(1))
        out["budget_to"] = int(rng.group(2))
    else:
        up = re.search(r"до\s*(\d+)", t)
        if up:
            out["budget_to"] = int(up.group(1))
        approx = re.search(r"близько\s*(\d+)", t)
        if approx and not out["budget_to"]:
            v = int(approx.group(1))
            out["budget_from"], out["budget_to"] = max(0, v - 200), v + 200

    # валюта
    if any(h in t for h in USD_HINTS):
        out["currency_hint"] = "usd"
    elif any(h in t for h in EUR_HINTS):
        out["currency_hint"] = "eur"

    # дата: перша знайдена дата (dd.mm або dd.mm.yy)
    m = re.search(r"(\d{1,2})[.](\d{1,2})(?:[.](\d{2,4}))?", t)
    if m:
        d, mth, yy_raw = int(m.group(1)), int(m.group(2)), m.group(3)
        if yy_raw is None:
            yy = int(datetime.now().strftime("%y"))
        else:
            yy_i = int(yy_raw)
            if yy_i >= 100:
                yy = yy_i % 100
            else:
                yy = yy_i
        out["date_from"] = f"{d:02d}.{mth:02d}.{yy:02d}"

    return out
