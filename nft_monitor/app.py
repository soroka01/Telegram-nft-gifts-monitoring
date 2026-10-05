from __future__ import annotations

import asyncio
import contextlib
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from .bot import build_router, set_bot_commands
from .config import AppConfig, ConfigError, load_config
from .fetcher import GiftFetcher
from .monitor import GiftMonitor
from .notifier import Notifier
from .state import StateStore


def setup_logging(config: AppConfig) -> None:
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%d.%m.%y %H:%M:%S",
    )
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    file_handler = logging.FileHandler(config.monitor.events_path.parent / "monitor.log", encoding="utf-8")
    file_handler.setFormatter(formatter)

    logging.basicConfig(level=logging.INFO, handlers=[console_handler, file_handler], force=True)
    for name in ("httpx", "httpcore", "aiogram", "aiohttp"):
        logging.getLogger(name).setLevel(logging.WARNING)


async def run(config: AppConfig) -> None:
    store = StateStore(config.monitor.state_path, config.monitor.events_path)
    fetcher = GiftFetcher(config.monitor)
    bot = Bot(config.bot.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    monitor = GiftMonitor(config, store, fetcher, Notifier(bot, config.bot.admin_ids))
    dp = Dispatcher()
    dp.include_router(build_router(monitor, config.bot.admin_ids))

    monitor_task = asyncio.create_task(monitor.run_loop())
    try:
        await set_bot_commands(bot)
        await dp.start_polling(bot)
    finally:
        monitor.stop()
        monitor_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await monitor_task
        await fetcher.close()
        await bot.session.close()


def main() -> None:
    try:
        config = load_config()
        config.monitor.events_path.parent.mkdir(parents=True, exist_ok=True)
        config.monitor.state_path.parent.mkdir(parents=True, exist_ok=True)
        setup_logging(config)
        asyncio.run(run(config))
    except ConfigError as exc:
        print(f"[CONFIG] {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        pass
