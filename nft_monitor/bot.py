from __future__ import annotations

from collections.abc import Awaitable, Callable, Collection
from typing import Any

from aiogram import BaseMiddleware, Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    TelegramObject,
)

from .messages import format_results, format_snapshot_summary, help_text
from .monitor import GiftMonitor
from .util import normalize_slug

DENIED_TEXT = "Нет доступа."
CHECKING_TEXT = "Проверяю NFT-подарки..."
EXAMPLE_SLUG = "ExampleGift-12345"


def main_keyboard() -> InlineKeyboardMarkup:
    def button(text: str, action: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(text=text, callback_data=f"ngm:{action}")

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [button("Статус", "status"), button("Проверить сейчас", "check")],
            [button("Подарки", "gifts"), button("Помощь", "help")],
        ]
    )


def command_args(message: Message) -> str:
    parts = (message.text or "").split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


async def edit_or_answer(message: Message, text: str) -> None:
    """Редактирует сообщение; если нельзя — отправляет новое. Повтор того же текста не ошибка."""
    try:
        await message.edit_text(text, reply_markup=main_keyboard())
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            await message.answer(text, reply_markup=main_keyboard())


class AdminOnlyMiddleware(BaseMiddleware):
    def __init__(self, admin_ids: Collection[int]) -> None:
        self.admin_ids = admin_ids

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user and user.id in self.admin_ids:
            return await handler(event, data)
        if isinstance(event, CallbackQuery):
            await event.answer(DENIED_TEXT, show_alert=True)
        elif isinstance(event, Message) and (event.text or "").startswith("/"):
            await event.answer(DENIED_TEXT)
        return None


def build_router(monitor: GiftMonitor, admin_ids: Collection[int]) -> Router:
    router = Router()
    guard = AdminOnlyMiddleware(admin_ids)
    router.message.outer_middleware(guard)
    router.callback_query.outer_middleware(guard)

    # --- команды -------------------------------------------------------------

    @router.message(CommandStart())
    @router.message(Command("help"))
    async def on_help(message: Message) -> None:
        await message.answer(help_text(), reply_markup=main_keyboard())

    @router.message(Command("status"))
    async def on_status(message: Message) -> None:
        await message.answer(monitor.status_text(), reply_markup=main_keyboard())

    @router.message(Command("gifts"))
    async def on_gifts(message: Message) -> None:
        await message.answer(monitor.gifts_text(), reply_markup=main_keyboard())

    @router.message(Command("snapshot"))
    async def on_snapshot(message: Message) -> None:
        slug = normalize_slug(command_args(message))
        if not slug:
            await message.answer(f"Укажи подарок: <code>/snapshot {EXAMPLE_SLUG}</code>")
            return
        snapshot = monitor.store.gift(slug)
        if snapshot is None:
            await message.answer(
                f"В state пока нет снимка для этого подарка. Запусти <code>/check {EXAMPLE_SLUG}</code>."
            )
            return
        await message.answer(format_snapshot_summary(snapshot, monitor.tz), reply_markup=main_keyboard())

    @router.message(Command("check"))
    async def on_check(message: Message) -> None:
        args = command_args(message)
        slug = normalize_slug(args) if args else None
        if args and not slug:
            await message.answer(f"Не понял slug. Пример: <code>/check {EXAMPLE_SLUG}</code>")
            return
        status = await message.answer(CHECKING_TEXT)
        results = await monitor.run_once(manual=True, notify_no_changes=True, only_slug=slug)
        await edit_or_answer(status, format_results(results))

    # --- inline-кнопки ----------------------------------------------------------

    panels: dict[str, Callable[[], str]] = {
        "status": monitor.status_text,
        "gifts": monitor.gifts_text,
        "help": help_text,
    }

    @router.callback_query(F.data.in_({f"ngm:{name}" for name in panels}))
    async def cb_panel(query: CallbackQuery) -> None:
        await query.answer()
        if isinstance(query.message, Message):
            await edit_or_answer(query.message, panels[query.data.removeprefix("ngm:")]())

    @router.callback_query(F.data == "ngm:check")
    async def cb_check(query: CallbackQuery) -> None:
        await query.answer("Запускаю проверку.")
        message = query.message if isinstance(query.message, Message) else None
        if message:
            await edit_or_answer(message, CHECKING_TEXT)
        results = await monitor.run_once(manual=True, notify_no_changes=True)
        if message:
            await edit_or_answer(message, format_results(results))

    return router


async def set_bot_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="status", description="статус мониторинга"),
            BotCommand(command="gifts", description="подарки и снимки"),
            BotCommand(command="check", description="проверить сейчас"),
            BotCommand(command="snapshot", description="последний снимок подарка"),
            BotCommand(command="help", description="помощь"),
        ]
    )
