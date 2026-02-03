import argparse
import asyncio
import logging
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiogram.enums import ParseMode

from app import config
from app.handlers import search as h_search
from app.handlers import logs as h_logs
from app.handlers import callbacks as h_callbacks

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    handlers=[
        logging.FileHandler(config.LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

def build_dp() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(h_search.router)
    dp.include_router(h_logs.router)
    dp.include_router(h_callbacks.router)
    return dp

async def on_startup(bot: Bot) -> None:
    if config.WEBHOOK_URL:
        await bot.set_webhook(config.WEBHOOK_URL, secret_token=config.WEBHOOK_SECRET)

def build_app(bot: Bot, dp: Dispatcher) -> web.Application:
    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=config.WEBHOOK_SECRET).register(app, path='/')
    setup_application(app, dp, bot=bot)
    return app

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--polling', action='store_true')
    parser.add_argument('--webhook', action='store_true')
    parser.add_argument('--webhook-url', default=None)
    args = parser.parse_args()

    token = config.TELEGRAM_BOT_TOKEN
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is required")

    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = build_dp()

    if args.polling or not args.webhook:
        logging.info("Starting polling mode…")
        await dp.start_polling(bot)
        return

    if args.webhook_url:
        config.WEBHOOK_URL = args.webhook_url

    if not config.WEBHOOK_URL:
        raise SystemExit("WEBHOOK_URL is required for webhook mode")

    await on_startup(bot)

    app = build_app(bot, dp)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host='0.0.0.0', port=8080)
    logging.info("Starting webhook server on :8080, path='/' → %s", config.WEBHOOK_URL)
    await site.start()

    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        logging.info("Shutting down…")

if __name__ == '__main__':
    asyncio.run(main())
