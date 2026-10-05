from __future__ import annotations

import re
from typing import Any

from .models import CheckResult
from .util import Tz, clean_text, code_text, format_dt, gift_url, html_attr, html_escape

MAX_BOT_MESSAGE = 4096

FIELD_LABELS = {
    "page_status": "статус страницы",
    "title": "название",
    "collection": "коллекция",
    "number": "номер",
    "owner_text": "владелец",
    "owner_url": "ссылка владельца",
    "owner_address": "TON-адрес владельца",
    "owner_photo_url": "аватар владельца",
    "model_name": "модель",
    "model_rarity": "редкость модели",
    "backdrop_name": "фон",
    "backdrop_rarity": "редкость фона",
    "symbol_name": "символ",
    "symbol_rarity": "редкость символа",
    "quantity_text": "кол-во",
    "issued_count": "выпущено",
    "total_count": "всего",
    "original_sender": "исходный отправитель",
    "original_sender_url": "ссылка исходного отправителя",
    "original_recipient": "исходный получатель",
    "original_date": "исходная дата",
    "original_footer": "исходные данные",
    "image_url": "картинка",
}

_PROFILE_RE = re.compile(r"^(?:https?://)?telegram\.me/([A-Za-z0-9_]{5,32})/?$")


def split_message(text: str, limit: int = MAX_BOT_MESSAGE) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.splitlines():
        line_len = len(line) + 1
        if line_len > limit:
            if current:
                chunks.append("\n".join(current))
                current, current_len = [], 0
            chunks.append(line[: limit - 3] + "...")
            continue
        if current and current_len + line_len > limit:
            chunks.append("\n".join(current))
            current, current_len = [], 0
        current.append(line)
        current_len += line_len
    if current:
        chunks.append("\n".join(current))
    return chunks


def gift_header(snapshot: dict[str, Any]) -> str:
    slug = snapshot.get("slug") or "unknown"
    title = snapshot.get("gift", {}).get("title") or slug
    return f'<a href="{html_attr(gift_url(slug))}">{html_escape(title)}</a>'


def value_text(value: Any) -> str:
    if value in (None, ""):
        return "нет"
    if isinstance(value, bool):
        return "да" if value else "нет"
    return str(value)


def _profile_link(value: Any) -> str | None:
    match = _PROFILE_RE.match(str(value or "").strip())
    if not match:
        return None
    username = match.group(1)
    return f'<a href="https://telegram.me/{html_attr(username)}">@{html_escape(username)}</a>'


def change_value_html(field: str, value: Any) -> str:
    if value in (None, ""):
        return "нет"
    if field == "owner_url" and (link := _profile_link(value)):
        return link
    return code_text(value_text(value))


def change_line(change: dict[str, Any]) -> str:
    field = change["field"]
    label = FIELD_LABELS.get(field, field)
    return f"{html_escape(label)}: {change_value_html(field, change.get('old'))} -> {change_value_html(field, change.get('new'))}"


def trait_line(label: str, name: Any, rarity: Any) -> str:
    if name in (None, ""):
        return f"{label}: нет"
    suffix = f" {html_escape(rarity)}" if rarity not in (None, "") else ""
    return f"{label}: {html_escape(name)}{suffix}"


def display_quantity(value: Any) -> str:
    text = re.sub(r"\s+issued$", "", clean_text(value), flags=re.IGNORECASE).strip()
    return text or "нет"


def format_snapshot_summary(snapshot: dict[str, Any], tz: Tz, title: str = "Снимок NFT-подарка") -> str:
    gift = snapshot.get("gift", {})
    lines = [
        f"<b>{html_escape(title)}</b>",
        gift_header(snapshot),
        f"снимок: {html_escape(format_dt(snapshot.get('taken_at'), tz))}",
        f"статус: {html_escape(value_text(snapshot.get('page_status')))}",
        "",
        f"владелец: {html_escape(value_text(gift.get('owner_text') or gift.get('owner_address')))}",
        trait_line("модель", gift.get("model_name"), gift.get("model_rarity")),
        trait_line("фон", gift.get("backdrop_name"), gift.get("backdrop_rarity")),
        trait_line("символ", gift.get("symbol_name"), gift.get("symbol_rarity")),
        f"кол-во: {html_escape(display_quantity(gift.get('quantity_text')))}",
    ]
    if gift.get("original_footer"):
        lines.append(f"исходные данные: {html_escape(gift['original_footer'])}")
    return "\n".join(lines)


def format_diff(snapshot: dict[str, Any], changes: list[dict[str, Any]], tz: Tz) -> str:
    lines = [
        "<b>Изменения NFT-подарка</b>",
        gift_header(snapshot),
        f"снимок: <code>{html_escape(format_dt(snapshot.get('taken_at'), tz))}</code>",
        "",
    ]
    lines.extend(change_line(change) for change in changes)
    return "\n".join(lines)


def format_unchanged(snapshot: dict[str, Any], tz: Tz) -> str:
    return (
        f"<b>Без изменений</b>\n{gift_header(snapshot)}\n"
        f"снимок: <code>{html_escape(format_dt(snapshot.get('taken_at'), tz))}</code>"
    )


def _result_status(item: CheckResult) -> str:
    if item.baseline:
        return "первый снимок"
    if item.changed:
        return "есть изменения"
    if item.ignored_only:
        return "только тихие изменения"
    if item.not_modified:
        return "не изменялся"
    return "без изменений"


def format_results(results: list[CheckResult]) -> str:
    ok = sum(item.ok for item in results)
    changed = sum(item.changed for item in results)
    baseline = sum(item.baseline for item in results)
    ignored = sum(item.ignored_only for item in results)
    lines = [
        "<b>Проверка NFT-подарков завершена</b>",
        f"подарков: <code>{len(results)}</code>, успешно: <code>{ok}</code>, изменений: <code>{changed}</code>, "
        f"только тихих: <code>{ignored}</code>, новых: <code>{baseline}</code>",
        "",
    ]
    for item in results:
        slug = html_escape(item.slug)
        if item.ok:
            lines.append(f"• <code>{slug}</code>: {_result_status(item)}")
        else:
            lines.append(f"• <code>{slug}</code>: ошибка <code>{html_escape(item.error)}</code>")
    return "\n".join(lines)


def help_text() -> str:
    return (
        "<b>NFT Gift Monitor</b>\n"
        "Команды:\n"
        "/status - состояние мониторинга\n"
        "/gifts - список подарков и последние снимки\n"
        "/check - проверить все подарки сейчас\n"
        "/check ExampleGift-12345 - разово проверить один подарок\n"
        "/snapshot ExampleGift-12345 - показать последний снимок из state\n\n"
        "В config указывай slug подарка, например <code>ExampleGift-12345</code>. "
        "Ссылка строится как <code>https://telegram.me/nft/ExampleGift-12345</code>."
    )
