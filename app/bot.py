import argparse
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from app import config
from app.handlers import callbacks as h_callbacks
from app.handlers import logs as h_logs
from app.handlers import search as h_search


# ---------------------------
# Settings / CLI
# ---------------------------

@dataclass
class RunSettings:
    mode: str  # "polling" | "webhook"
    webhook_url: Optional[str] = None
    host: str = "0.0.0.0"
    port: int = 8080
    path: str = "/"


def parse_args() -> RunSettings:
    parser = argparse.ArgumentParser(description="Telegram bot runner (aiogram v3)")

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--polling", action="store_true", help="Run bot in polling mode")
    mode.add_argument("--webhook", action="store_true", help="Run bot in webhook mode")

    parser.add_argument("--webhook-url", default=None, help="Override WEBHOOK_URL from config")
    parser.add_argument("--host", default="0.0.0.0", help="Webhook server host")
    parser.add_argument("--port", type=int, default=8080, help="Webhook server port")
    parser.add_argument("--path", default="/", help="Webhook endpoint path (default '/')")

    args = parser.parse_args()

    if args.webhook:
        mode_name = "webhook"
    else:
        # default = polling (як у тебе було)
        mode_name = "polling"

    return RunSettings(
        mode=mode_name,
        webhook_url=args.webhook_url,
        host=args.host,
        port=args.port,
        path=args.path,
    )


# ---------------------------
# Logging
# ---------------------------

def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(config.LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


# ---------------------------
# Bot / Dispatcher
# ---------------------------

def build_bot() -> Bot:
    token = config.TELEGRAM_BOT_TOKEN
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is required")
    return Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(h_search.router)
    dp.include_router(h_logs.router)
    dp.include_router(h_callbacks.router)
    return dp


# ---------------------------
# Webhook lifecycle
# ---------------------------

async def set_webhook(bot: Bot, webhook_url: str) -> None:
    if not config.WEBHOOK_SECRET:
        raise SystemExit("WEBHOOK_SECRET is required for webhook mode")

    await bot.set_webhook(
        webhook_url,
        secret_token=config.WEBHOOK_SECRET,
        drop_pending_updates=True,
    )
    logging.info("Webhook set: %s", webhook_url)


async def delete_webhook(bot: Bot) -> None:
    # корисно при перемиканні на polling
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logging.info("Webhook deleted")
    except Exception:
        logging.exception("Failed to delete webhook")


def build_web_app(bot: Bot, dp: Dispatcher, path: str) -> web.Application:
    app = web.Application()

    # handler webhook
    SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=config.WEBHOOK_SECRET,
    ).register(app, path=path)

    # підключення lifecycle aiogram
    setup_application(app, dp, bot=bot)
    return app


async def run_webhook(bot: Bot, dp: Dispatcher, settings: RunSettings) -> None:
    webhook_url = settings.webhook_url or config.WEBHOOK_URL
    if not webhook_url:
        raise SystemExit("WEBHOOK_URL is required for webhook mode (or pass --webhook-url)")

    await set_webhook(bot, webhook_url)

    app = build_web_app(bot, dp, path=settings.path)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, host=settings.host, port=settings.port)
    await site.start()

    logging.info(
        "Webhook server started: http://%s:%s%s -> %s",
        settings.host,
        settings.port,
        settings.path,
        webhook_url,
    )

    # Правильний “hold” без while True:
    # aiohttp runner тримає цикл, але нам треба не завершувати main.
    stop_event = asyncio.Event()
    try:
        await stop_event.wait()
    finally:
        logging.info("Stopping webhook server…")
        await runner.cleanup()


# ---------------------------
# Polling
# ---------------------------

async def run_polling(bot: Bot, dp: Dispatcher) -> None:
    # Якщо раніше був webhook — краще прибрати
    await delete_webhook(bot)
    logging.info("Starting polling mode…")
    await dp.start_polling(bot)


# ---------------------------
# Main
# ---------------------------

async def main() -> None:
    setup_logging()
    settings = parse_args()

    bot = build_bot()
    dp = build_dispatcher()

    try:
        if settings.mode == "polling":
            await run_polling(bot, dp)
        else:
            await run_webhook(bot, dp, settings)
    except (KeyboardInterrupt, SystemExit):
        logging.info("Shutting down…")
    finally:
        try:
            await bot.session.close()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
