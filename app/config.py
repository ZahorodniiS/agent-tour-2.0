import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ENABLE_LLM = os.getenv("ENABLE_LLM", "false").lower() in ("1","true","yes")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")

ITTOUR_API_TOKEN = os.getenv("ITTOUR_API_TOKEN", "")
ACCEPT_LANGUAGE = os.getenv("ACCEPT_LANGUAGE", "uk")
CURRENCY_DEFAULT = int(os.getenv("CURRENCY_DEFAULT", "2"))  # 2=UAH

WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "bot.log")

DEFAULTS = {
    "type": 1,
    "kind": 1,
    "hotel_rating": 78,
    "adult_amount": 2,
    "child_amount": 0,
    "night_from": 6,
    "night_till": 8,
    "currency": int(os.getenv("CURRENCY_DEFAULT", "2")),
    "items_per_page": 10,
    "price_from": 100,
    "price_till": 500_000,
}

DATA_DIR = os.path.join(BASE_DIR, "data")
COUNTRY_MAP_FILE = os.path.join(DATA_DIR, "country_map.json")
FROM_CITY_MAP_FILE = os.path.join(DATA_DIR, "from_city_map.json")
