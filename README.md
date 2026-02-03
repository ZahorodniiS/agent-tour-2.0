# Telegram Travel Bot (ITTour) — з LLM-агентом
Стек: Python 3.11+, **aiogram v3**, **aiohttp**, **OpenAI** (LLM), Ubuntu 22.04, SQLite (резерв), Webhook/Polling.
Мова інтерфейсу: `uk`, валюта за замовчуванням: `UAH=2`.

## Можливості
- Розбір вільного тексту клієнта (LLM + rule-based fallback).
- Валідація обов’язкових полів під **/module/search-list**.
- Автодоповнення дефолтами: `type=1`, `kind=1`, `hotel_rating=78`, `adult=2`, `child=0`, `night 6..8`, `date_from=today+2`, `date_till=+12`, `currency=UAH`.
- Конвертація згаданої валюти (USD/EUR/UAH).
- Формування запиту до ITTour, відправка і показ **10** пропозицій картками (з фото).
- Логи у `./logs/bot.log` + `/logs` надсилає файл в чат.
- Аналіз помилок API (100..445): пояснення + дружні підказки та авто-виправлення (якщо можливо).
- Кешування частково введених параметрів між уточненнями.

## Швидкий старт (локально, polling)
```bash
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt

cp .env.example .env
# відредагуйте .env: TELEGRAM_BOT_TOKEN, ITTOUR_API_TOKEN, (опц.) OPENAI_API_KEY
python app/bot.py --polling
```

## Webhook
```bash
python app/bot.py --webhook --webhook-url=https://YOUR_DOMAIN/bot
```

## Налаштування
- `ENABLE_LLM=true` в `.env` — увімкнути LLM (модель gpt-5-mini за замовчуванням).
- Мапи країн/міст у **data/country_map.json**, **data/from_city_map.json**.

## Приклад запиту
> «Туреччина на 2 дорослих з Києва з 02.11, бюджет до 2000 дол»
