from __future__ import annotations

import hashlib
import html
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "Europe/Moscow"

SLUG_RE = re.compile(r"[A-Za-z0-9]+-\d+")
SPACE_RE = re.compile(r"\s+")
_NFT_URL_RE = re.compile(r"^(?:https?://)?(?:t\.me|telegram\.(?:me|dog))/nft/([^/?#\s]+)", re.IGNORECASE)
_NFT_SCHEME_RE = re.compile(r"^tg://nft\?(?:[^#\s]*&)?slug=([^&#\s]+)", re.IGNORECASE)

Tz = timezone | ZoneInfo


def normalize_slug(value: Any) -> str:
    """Принимает slug, https://t.me/nft/<slug> или tg://nft?slug=<slug>; при ошибке возвращает ''."""
    text = str(value or "").strip()
    match = _NFT_URL_RE.match(text) or _NFT_SCHEME_RE.match(text)
    candidate = match.group(1) if match else text
    return candidate if SLUG_RE.fullmatch(candidate) else ""


def gift_url(slug: str) -> str:
    return f"https://telegram.me/nft/{slug}"


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = html.unescape(str(value)).replace("\xa0", " ")
    return SPACE_RE.sub(" ", text).strip()


def int_from_spaced(value: str) -> int | None:
    digits = re.sub(r"\D+", "", value or "")
    return int(digits) if digits else None


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def safe_dir_name(value: Any) -> str:
    return re.sub(r"[^0-9A-Za-z_-]+", "_", str(value or "")).strip("_") or "unknown"


# --- время -----------------------------------------------------------------


def get_timezone(name: str) -> Tz:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        logging.warning("Unknown timezone %s, using %s", name, DEFAULT_TIMEZONE)
        return ZoneInfo(DEFAULT_TIMEZONE)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat(timespec="seconds")


def parse_iso_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def format_dt(value: Any, tz: Tz) -> str:
    dt = value if isinstance(value, datetime) else parse_iso_datetime(value)
    if dt is None:
        return "нет"
    local = dt.astimezone(tz)
    suffix = "МСК" if getattr(tz, "key", "") == "Europe/Moscow" else local.tzname() or "local"
    return local.strftime("%d.%m.%y %H:%M:%S") + f" {suffix}"


# --- HTML для Telegram -----------------------------------------------------


def html_escape(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=False)


def html_attr(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def code_text(value: Any) -> str:
    text = "нет" if value in (None, "") else str(value)
    return f"<code>{html_escape(text)}</code>"


def gift_link(slug: str) -> str:
    return f'<a href="{html_attr(gift_url(slug))}">{html_escape(slug)}</a>'


def compact_text(value: Any, limit: int = 90) -> str:
    text = clean_text(value)
    if not text:
        return "нет"
    return text[: limit - 3] + "..." if len(text) > limit else text
