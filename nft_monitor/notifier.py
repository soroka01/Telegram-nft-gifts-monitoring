from __future__ import annotations

import logging
from collections.abc import Collection

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import LinkPreviewOptions

from .messages import split_message


class Notifier:
    """Рассылает сообщения всем администраторам."""

    def __init__(self, bot: Bot, admin_ids: Collection[int]) -> None:
        self.bot = bot
        self.admin_ids = admin_ids

    async def send(self, text: str, disable_web_page_preview: bool = False) -> None:
        chunks = split_message(text)
        preview = LinkPreviewOptions(is_disabled=disable_web_page_preview)
        for chunk in chunks:
            for admin_id in self.admin_ids:
                try:
                    await self.bot.send_message(admin_id, chunk, link_preview_options=preview)
                except TelegramAPIError:
                    logging.exception("Failed to send message to admin %s", admin_id)
