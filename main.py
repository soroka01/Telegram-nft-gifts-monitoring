from __future__ import annotations

import asyncio
import hashlib
import html
import json
import logging
import os
import random
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from bs4 import BeautifulSoup


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
DEFAULT_ADMIN_ID = 123456789
MAX_BOT_MESSAGE = 4096
SCHEMA_VERSION = 1
LOGGER = logging.getLogger("nft-monitor")

SLUG_RE = re.compile(r"^[A-Za-z0-9]+-\d+$")
SPACE_RE = re.compile(r"\s+")

IGNORED_NOTIFY_FIELDS = {
    "quantity_text",
    "issued_count",
    "total_count",
    "original_sender",
    "original_sender_url",
    "original_recipient",
    "original_date",
    "original_footer",
}

DIFF_FIELDS = {
    "page_status",
    "title",
    "collection",
    "number",
    "owner_text",
    "owner_url",
    "owner_address",
    "owner_photo_url",
    "model_name",
    "model_rarity",
    "backdrop_name",
    "backdrop_rarity",
    "symbol_name",
    "symbol_rarity",
    "quantity_text",
    "issued_count",
    "total_count",
    "original_sender",
    "original_sender_url",
    "original_recipient",
    "original_date",
    "original_footer",
    "image_url",
}

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


class ConfigError(RuntimeError):
    pass


class FetchError(RuntimeError):
    pass


@dataclass(frozen=True)
class BotConfig:
    token: str
    admin_ids: set[int]


@dataclass(frozen=True)
class MonitorConfig:
    targets: list[str]
    interval_seconds: int
    request_timeout_seconds: float
    request_delay_seconds: float
    jitter_seconds: float
    error_backoff_seconds: int
    notify_initial_snapshot: bool
    notify_errors: bool
    track_image_url: bool
    timezone_name: str
    state_path: Path
    events_path: Path
    user_agent: str


@dataclass(frozen=True)
class AppConfig:
    bot: BotConfig
    monitor: MonitorConfig


@dataclass
class FetchResult:
    snapshot: dict[str, Any] | None
    not_modified: bool = False
    status_code: int | None = None


@dataclass
class CheckResult:
    slug: str
    ok: bool
    changed: bool = False
    baseline: bool = False
    not_modified: bool = False
    ignored_only: bool = False
    error: str | None = None


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Не найден {path}. Скопируй config.example.json в config.json.")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Ошибка JSON в {path}: {exc}") from exc


def env_or_value(env_name: str, value: Any) -> Any:
    env_value = os.getenv(env_name)
    return env_value if env_value not in (None, "") else value


def parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on", "да"}


def parse_admin_ids(raw: Any) -> set[int]:
    if raw in (None, ""):
        return {DEFAULT_ADMIN_ID}
    if isinstance(raw, int):
        return {raw}
    if isinstance(raw, str):
        chunks = [item.strip() for item in raw.split(",")]
    else:
        chunks = [str(item).strip() for item in raw]
    ids = {int(item) for item in chunks if item}
    return ids or {DEFAULT_ADMIN_ID}


def normalize_slug(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = text.rstrip("/")
    if "t.me/nft/" in text:
        text = text.rsplit("/", 1)[-1]
    if text.startswith("tg://nft?slug="):
        text = text.split("slug=", 1)[-1].split("&", 1)[0]
    text = text.strip()
    return text if SLUG_RE.match(text) else ""


def parse_targets(raw: Any) -> list[str]:
    if isinstance(raw, str):
        values = [item.strip() for item in raw.split(",")]
    else:
        values = raw or []

    targets: list[str] = []
    for item in values:
        if isinstance(item, dict):
            if parse_bool(item.get("enabled"), True) is False:
                continue
            item = item.get("slug") or item.get("target") or item.get("url")
        slug = normalize_slug(item)
        if slug and slug not in targets:
            targets.append(slug)
    return targets


def validate_secret(name: str, value: Any) -> str:
    text = str(value or "").strip()
    if not text or text.startswith("PUT_") or text.startswith("YOUR_"):
        raise ConfigError(f"Заполни {name} в config.json или через переменную окружения.")
    return text


def resolve_path(raw: Any, default: str) -> Path:
    path = Path(str(raw or default).strip())
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def load_config() -> AppConfig:
    raw = load_json(CONFIG_PATH)
    bot_raw = raw.get("bot", {})
    monitor_raw = raw.get("monitor", {})

    token = validate_secret("bot.token", env_or_value("BOT_TOKEN", bot_raw.get("token")))
    admin_ids = parse_admin_ids(env_or_value("ADMIN_IDS", bot_raw.get("admin_ids", bot_raw.get("admin_id"))))
    targets = parse_targets(env_or_value("NFT_GIFT_TARGETS", monitor_raw.get("targets", [])))
    if not targets:
        raise ConfigError("Добавь хотя бы один NFT-подарок в monitor.targets, например ExampleGift-12345.")

    monitor = MonitorConfig(
        targets=targets,
        interval_seconds=max(5, int(monitor_raw.get("interval_seconds", 30))),
        request_timeout_seconds=max(2.0, float(monitor_raw.get("request_timeout_seconds", 10))),
        request_delay_seconds=max(0.0, float(monitor_raw.get("request_delay_seconds", 0.25))),
        jitter_seconds=max(0.0, float(monitor_raw.get("jitter_seconds", 3))),
        error_backoff_seconds=max(0, int(monitor_raw.get("error_backoff_seconds", 120))),
        notify_initial_snapshot=parse_bool(monitor_raw.get("notify_initial_snapshot", True), True),
        notify_errors=parse_bool(monitor_raw.get("notify_errors", True), True),
        track_image_url=parse_bool(monitor_raw.get("track_image_url", False), False),
        timezone_name=str(monitor_raw.get("timezone", "Europe/Moscow")),
        state_path=resolve_path(monitor_raw.get("state_path"), "state/nft_gift_state.json"),
        events_path=resolve_path(monitor_raw.get("events_path"), "logs/nft_gift_events.jsonl"),
        user_agent=str(monitor_raw.get("user_agent") or "Mozilla/5.0"),
    )
    return AppConfig(bot=BotConfig(token=token, admin_ids=admin_ids), monitor=monitor)


def ensure_dirs(config: AppConfig) -> None:
    config.monitor.state_path.parent.mkdir(parents=True, exist_ok=True)
    config.monitor.events_path.parent.mkdir(parents=True, exist_ok=True)


def setup_logging(config: AppConfig) -> None:
    log_path = config.monitor.events_path.parent / "monitor.log"
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%d.%m.%y %H:%M:%S",
    )
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)

    logging.basicConfig(
        level=logging.INFO,
        handlers=[console_handler, file_handler],
        force=True,
    )
    for logger_name in ("httpx", "httpcore", "aiogram", "aiohttp"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def get_timezone(name: str) -> timezone | ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        logging.warning("Unknown timezone %s, using Europe/Moscow", name)
        return ZoneInfo("Europe/Moscow")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_iso_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def format_dt(value: Any, tz: timezone | ZoneInfo) -> str:
    dt = parse_iso_datetime(value)
    if dt is None:
        return "нет"
    local = dt.astimezone(tz)
    suffix = "МСК" if getattr(tz, "key", "") == "Europe/Moscow" else local.tzname() or "local"
    return local.strftime("%d.%m.%y %H:%M:%S") + f" {suffix}"


def html_escape(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=False)


def html_attr(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def code_text(value: Any) -> str:
    text = "нет" if value in (None, "") else str(value)
    return f"<code>{html_escape(text)}</code>"


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


def gift_url(slug: str) -> str:
    return f"https://t.me/nft/{slug}"


def safe_dir_name(value: Any) -> str:
    return re.sub(r"[^0-9A-Za-z_-]+", "_", str(value or "")).strip("_") or "unknown"


class StateStore:
    def __init__(self, path: Path, events_path: Path) -> None:
        self.path = path
        self.events_path = events_path
        self.gift_events_dir = events_path.parent / "gifts"
        self.data = self._load()

    @staticmethod
    def _empty_state() -> dict[str, Any]:
        return {
            "schema": SCHEMA_VERSION,
            "created_at": utc_now_iso(),
            "updated_at": None,
            "gifts": {},
        }

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty_state()
        try:
            text = self.path.read_text(encoding="utf-8-sig").strip()
            if not text:
                return self._empty_state()
            data = json.loads(text)
        except json.JSONDecodeError:
            backup = self.path.with_suffix(self.path.suffix + f".broken-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
            try:
                self.path.replace(backup)
                logging.error("Broken state moved to %s", backup)
            except OSError:
                logging.exception("Cannot move broken state")
            return self._empty_state()
        data.setdefault("schema", SCHEMA_VERSION)
        data.setdefault("gifts", {})
        return data

    def save(self) -> None:
        self.data["updated_at"] = utc_now_iso()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.path)

    def gift(self, slug: str) -> dict[str, Any] | None:
        return self.data.get("gifts", {}).get(slug)

    def upsert_gift(self, slug: str, snapshot: dict[str, Any]) -> None:
        self.data.setdefault("gifts", {})[slug] = snapshot
        self.save()

    def append_event(self, event: dict[str, Any]) -> None:
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        event.setdefault("created_at", utc_now_iso())
        payload = json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
        with self.events_path.open("a", encoding="utf-8") as file:
            file.write(payload)

        slug = event.get("slug") or event.get("snapshot", {}).get("slug")
        if slug:
            gift_dir = self.gift_events_dir / safe_dir_name(slug)
            gift_dir.mkdir(parents=True, exist_ok=True)
            with (gift_dir / self.events_path.name).open("a", encoding="utf-8") as file:
                file.write(payload)

    def all_gifts(self) -> list[dict[str, Any]]:
        return list(self.data.get("gifts", {}).values())


def meta_content(soup: BeautifulSoup, key: str) -> str | None:
    tag = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
    if not tag:
        return None
    value = tag.get("content")
    return clean_text(value) if value is not None else None


def meta_raw_content(soup: BeautifulSoup, key: str) -> str | None:
    tag = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
    if not tag:
        return None
    value = tag.get("content")
    return str(value).strip() if value is not None else None


def parse_trait_cell(cell: Any) -> tuple[str | None, str | None]:
    mark = cell.find("mark") if cell else None
    rarity = clean_text(mark.get_text(" ")) if mark else None
    if mark:
        mark.extract()
    name = clean_text(cell.get_text(" ")) if cell else ""
    return name or None, rarity or None


def parse_quantity(value: str) -> tuple[str | None, int | None, int | None]:
    text = clean_text(value)
    match = re.search(r"([\d\s]+)\s*/\s*([\d\s]+)", text)
    if not match:
        return text or None, None, None
    return text, int_from_spaced(match.group(1)), int_from_spaced(match.group(2))


def parse_owner_cell(cell: Any) -> dict[str, Any]:
    owner: dict[str, Any] = {
        "owner_text": clean_text(cell.get_text(" ")) if cell else None,
        "owner_url": None,
        "owner_address": None,
        "owner_photo_url": None,
    }
    if not cell:
        return owner

    address = cell.select_one(".tgme_gift_owner_address")
    if address:
        owner["owner_address"] = clean_text(address.get_text(" ")) or None
    link = cell.find("a", href=True)
    if link:
        owner["owner_url"] = urljoin("https://t.me/", link["href"])
    image = cell.find("img", src=True)
    if image:
        owner["owner_photo_url"] = urljoin("https://t.me/", image["src"])
    return owner


def parse_original_footer(footer: Any) -> dict[str, Any]:
    data = {
        "original_footer": None,
        "original_sender": None,
        "original_sender_url": None,
        "original_recipient": None,
        "original_date": None,
    }
    if not footer:
        return data

    text = clean_text(footer.get_text(" "))
    data["original_footer"] = text or None
    link = footer.find("a", href=True)
    if link:
        data["original_sender"] = clean_text(link.get_text(" ")) or None
        data["original_sender_url"] = urljoin("https://t.me/", link["href"])

    match = re.match(r"Gifted by (.*?) to (.*?) on (.*)$", text)
    if match:
        data["original_sender"] = data["original_sender"] or clean_text(match.group(1)) or None
        data["original_recipient"] = clean_text(match.group(2)) or None
        data["original_date"] = clean_text(match.group(3)) or None
    return data


def parse_title(title: str | None, slug: str) -> tuple[str, str | None, int | None]:
    clean = clean_text(title) or slug
    match = re.match(r"(.+?)\s+#(\d+)$", clean)
    if not match:
        return clean, None, None
    return clean, clean_text(match.group(1)) or None, int(match.group(2))


def parse_gift_html(slug: str, content: str, response: httpx.Response) -> dict[str, Any]:
    soup = BeautifulSoup(content, "html.parser")
    title, collection, number = parse_title(meta_content(soup, "og:title"), slug)
    gift: dict[str, Any] = {
        "title": title,
        "collection": collection,
        "number": number,
        "image_url": meta_raw_content(soup, "og:image"),
        "description": meta_raw_content(soup, "og:description"),
        "telegram_app_url": meta_raw_content(soup, "al:ios:url") or f"tg://nft?slug={slug}",
        "owner_text": None,
        "owner_url": None,
        "owner_address": None,
        "owner_photo_url": None,
        "model_name": None,
        "model_rarity": None,
        "backdrop_name": None,
        "backdrop_rarity": None,
        "symbol_name": None,
        "symbol_rarity": None,
        "quantity_text": None,
        "issued_count": None,
        "total_count": None,
        "original_sender": None,
        "original_sender_url": None,
        "original_recipient": None,
        "original_date": None,
        "original_footer": None,
    }

    table_found = False
    for row in soup.select("table.tgme_gift_table tr"):
        footer = row.find("th", class_="footer")
        if footer:
            gift.update(parse_original_footer(footer))
            continue

        header = row.find("th")
        cell = row.find("td")
        key = clean_text(header.get_text(" ")) if header else ""
        if not key or cell is None:
            continue
        table_found = True

        if key == "Owner":
            gift.update(parse_owner_cell(cell))
        elif key == "Model":
            gift["model_name"], gift["model_rarity"] = parse_trait_cell(cell)
        elif key == "Backdrop":
            gift["backdrop_name"], gift["backdrop_rarity"] = parse_trait_cell(cell)
        elif key == "Symbol":
            gift["symbol_name"], gift["symbol_rarity"] = parse_trait_cell(cell)
        elif key == "Quantity":
            quantity, issued, total = parse_quantity(cell.get_text(" "))
            gift["quantity_text"] = quantity
            gift["issued_count"] = issued
            gift["total_count"] = total

    page_status = "ok" if table_found else "no_gift_table"
    if response.status_code >= 400:
        page_status = f"http_{response.status_code}"

    snapshot = {
        "schema": SCHEMA_VERSION,
        "slug": slug,
        "url": gift_url(slug),
        "taken_at": utc_now_iso(),
        "page_status": page_status,
        "gift": gift,
        "http": {
            "status_code": response.status_code,
            "etag": response.headers.get("etag"),
            "last_modified": response.headers.get("last-modified"),
            "content_hash": hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest(),
        },
    }
    snapshot["digest"] = stable_hash(watched_payload(snapshot, track_image_url=True))
    return snapshot


def watched_payload(snapshot: dict[str, Any], track_image_url: bool) -> dict[str, Any]:
    gift = snapshot.get("gift", {})
    fields = set(DIFF_FIELDS)
    if not track_image_url:
        fields.discard("image_url")

    payload: dict[str, Any] = {"page_status": snapshot.get("page_status")}
    for field in fields:
        if field == "page_status":
            continue
        payload[field] = gift.get(field)
    return payload


def all_diff_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    gift = snapshot.get("gift", {})
    payload: dict[str, Any] = {"page_status": snapshot.get("page_status")}
    for field in DIFF_FIELDS:
        if field == "page_status":
            continue
        payload[field] = gift.get(field)
    return payload


def diff_snapshots(old: dict[str, Any], new: dict[str, Any], track_image_url: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    old_all = all_diff_payload(old)
    new_all = all_diff_payload(new)
    all_changes: list[dict[str, Any]] = []
    for field in sorted(set(old_all) | set(new_all)):
        old_value = old_all.get(field)
        new_value = new_all.get(field)
        if old_value != new_value:
            all_changes.append({"field": field, "old": old_value, "new": new_value})

    ignored_fields = set(IGNORED_NOTIFY_FIELDS)
    if not track_image_url:
        ignored_fields.add("image_url")
    notify_changes = [change for change in all_changes if change["field"] not in ignored_fields]
    return all_changes, notify_changes


class GiftFetcher:
    def __init__(self, config: MonitorConfig) -> None:
        headers = {
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "accept-language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "cache-control": "no-cache",
            "user-agent": config.user_agent,
        }
        self.client = httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(config.request_timeout_seconds),
            follow_redirects=True,
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def fetch(self, slug: str, previous: dict[str, Any] | None = None) -> FetchResult:
        headers: dict[str, str] = {}
        previous_http = (previous or {}).get("http", {})
        if previous_http.get("etag"):
            headers["if-none-match"] = str(previous_http["etag"])
        if previous_http.get("last_modified"):
            headers["if-modified-since"] = str(previous_http["last_modified"])

        response = await self.client.get(gift_url(slug), headers=headers)
        if response.status_code == 304:
            return FetchResult(snapshot=None, not_modified=True, status_code=response.status_code)
        if response.status_code in {429, 500, 502, 503, 504}:
            retry_after = response.headers.get("retry-after")
            suffix = f", retry-after {retry_after} сек." if retry_after else ""
            raise FetchError(f"HTTP {response.status_code}{suffix}")
        if response.status_code >= 400 and response.status_code != 404:
            raise FetchError(f"HTTP {response.status_code}")

        snapshot = parse_gift_html(slug, response.text, response)
        return FetchResult(snapshot=snapshot, status_code=response.status_code)


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


def change_line(change: dict[str, Any]) -> str:
    field = change["field"]
    label = FIELD_LABELS.get(field, field)
    old = value_text(change.get("old"))
    new = value_text(change.get("new"))
    return f"{html_escape(label)}: {code_text(old)} -> {code_text(new)}"


def trait_line(label: str, name: Any, rarity: Any) -> str:
    if name in (None, ""):
        return f"{label}: нет"
    suffix = f" {html_escape(rarity)}" if rarity not in (None, "") else ""
    return f"{label}: {html_escape(name)}{suffix}"


def display_quantity(value: Any) -> str:
    text = clean_text(value)
    text = re.sub(r"\s+issued$", "", text, flags=re.IGNORECASE).strip()
    return text or "нет"


def format_snapshot_summary(snapshot: dict[str, Any], tz: timezone | ZoneInfo, title: str = "Снимок NFT-подарка") -> str:
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
        lines.append(f"исходные данные: {html_escape(gift.get('original_footer'))}")
    return "\n".join(lines)


def format_diff(snapshot: dict[str, Any], changes: list[dict[str, Any]], tz: timezone | ZoneInfo) -> str:
    lines = [
        "<b>Изменения NFT-подарка</b>",
        gift_header(snapshot),
        f"снимок: <code>{html_escape(format_dt(snapshot.get('taken_at'), tz))}</code>",
        "",
    ]
    lines.extend(change_line(change) for change in changes)
    return "\n".join(lines)


def format_results(results: list[CheckResult]) -> str:
    ok = sum(1 for item in results if item.ok)
    changed = sum(1 for item in results if item.changed)
    baseline = sum(1 for item in results if item.baseline)
    ignored = sum(1 for item in results if item.ignored_only)
    lines = [
        "<b>Проверка NFT-подарков завершена</b>",
        f"подарков: <code>{len(results)}</code>, успешно: <code>{ok}</code>, изменений: <code>{changed}</code>, только тихих: <code>{ignored}</code>, новых: <code>{baseline}</code>",
        "",
    ]
    for item in results:
        if item.ok:
            if item.baseline:
                status = "первый снимок"
            elif item.changed:
                status = "есть изменения"
            elif item.ignored_only:
                status = "только тихие изменения"
            elif item.not_modified:
                status = "не изменялся"
            else:
                status = "без изменений"
            lines.append(f"• <code>{html_escape(item.slug)}</code>: {html_escape(status)}")
        else:
            lines.append(f"• <code>{html_escape(item.slug)}</code>: ошибка <code>{html_escape(item.error)}</code>")
    return "\n".join(lines)


def split_message(text: str) -> list[str]:
    if len(text) <= MAX_BOT_MESSAGE:
        return [text]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.splitlines():
        line_len = len(line) + 1
        if current and current_len + line_len > MAX_BOT_MESSAGE:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        if line_len > MAX_BOT_MESSAGE:
            chunks.append(line[: MAX_BOT_MESSAGE - 3] + "...")
            continue
        current.append(line)
        current_len += line_len
    if current:
        chunks.append("\n".join(current))
    return chunks


def compact_log_value(value: Any, limit: int = 90) -> str:
    text = clean_text(value)
    if not text:
        return "нет"
    return text[: limit - 3] + "..." if len(text) > limit else text


def log_check(status: str, slug: str, detail: str, started_at: float | None = None) -> None:
    elapsed = ""
    if started_at is not None:
        elapsed = f" | {int((time.perf_counter() - started_at) * 1000):>4} ms"
    LOGGER.info("%-7s | %-32s | %s%s", status, slug[:32], detail, elapsed)


class GiftMonitor:
    def __init__(self, config: AppConfig, store: StateStore, fetcher: GiftFetcher, bot: Bot) -> None:
        self.config = config
        self.store = store
        self.fetcher = fetcher
        self.bot = bot
        self.tz = get_timezone(config.monitor.timezone_name)
        self.lock = asyncio.Lock()
        self.stop_event = asyncio.Event()
        self.last_started_at: str | None = None
        self.last_finished_at: str | None = None
        self.last_error: str | None = None
        self.last_results: list[CheckResult] = []
        self.error_backoff_until: dict[str, datetime] = {}

    def stop(self) -> None:
        self.stop_event.set()

    async def run_loop(self) -> None:
        await self.send_admin_text(self.startup_text())
        while not self.stop_event.is_set():
            try:
                await self.run_once(manual=False, notify_no_changes=False)
            except Exception as exc:
                LOGGER.exception("LOOP    | failed")
                self.last_error = f"{type(exc).__name__}: {exc}"
                await self.send_admin_text(f"<b>Ошибка цикла мониторинга</b>\n<code>{html_escape(self.last_error)}</code>")

            timeout = self.config.monitor.interval_seconds
            if self.config.monitor.jitter_seconds:
                timeout += random.uniform(0, self.config.monitor.jitter_seconds)
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                pass

    def startup_text(self) -> str:
        targets = "\n".join(f"• {gift_link(slug)}" for slug in self.config.monitor.targets)
        return (
            "<b>NFT Gift Monitor запущен</b>\n"
            f"Интервал: <code>{self.config.monitor.interval_seconds} сек</code>\n"
            f"Подарков: <code>{len(self.config.monitor.targets)}</code>\n"
            f"Тихие поля: <code>кол-во, выпущено, исходный отправитель, исходный получатель</code>\n\n"
            f"{targets}"
        )

    def status_text(self) -> str:
        running = "идет проверка" if self.lock.locked() else "ожидает"
        lines = [
            "<b>Статус NFT Gift Monitor</b>",
            f"Состояние: <b>{running}</b>",
            f"Подарков в config: <code>{len(self.config.monitor.targets)}</code>",
            f"Интервал: <code>{self.config.monitor.interval_seconds} сек</code>",
            f"Последний старт: <code>{html_escape(format_dt(self.last_started_at, self.tz))}</code>",
            f"Последнее завершение: <code>{html_escape(format_dt(self.last_finished_at, self.tz))}</code>",
            f"State: <code>{html_escape(self.config.monitor.state_path)}</code>",
            f"Events: <code>{html_escape(self.config.monitor.events_path)}</code>",
        ]
        if self.last_error:
            lines.append(f"Последняя ошибка: <code>{html_escape(self.last_error)}</code>")
        if self.last_results:
            lines.append("")
            lines.append(format_results(self.last_results))
        return "\n".join(lines)

    def gifts_text(self) -> str:
        lines = ["<b>NFT-подарки из config</b>"]
        for slug in self.config.monitor.targets:
            snapshot = self.store.gift(slug)
            if snapshot:
                gift = snapshot.get("gift", {})
                owner = gift.get("owner_text") or gift.get("owner_address") or "нет"
                taken = format_dt(snapshot.get("taken_at"), self.tz)
                lines.append(f"• {gift_link(slug)} - владелец {code_text(owner)}, снят <code>{html_escape(taken)}</code>")
            else:
                lines.append(f"• {gift_link(slug)} - <code>пока не снят</code>")
        return "\n".join(lines)

    async def run_once(
        self,
        manual: bool,
        notify_no_changes: bool,
        only_slug: str | None = None,
    ) -> list[CheckResult]:
        if self.lock.locked():
            return [CheckResult(slug=only_slug or "all", ok=False, error="Проверка уже идет.")]

        targets = [only_slug] if only_slug else self.config.monitor.targets
        async with self.lock:
            run_started_at = time.perf_counter()
            self.last_started_at = utc_now_iso()
            self.last_error = None
            results: list[CheckResult] = []
            for index, slug in enumerate(targets):
                if index and self.config.monitor.request_delay_seconds:
                    await asyncio.sleep(self.config.monitor.request_delay_seconds)
                result = await self.check_gift(slug, manual=manual, notify_no_changes=notify_no_changes)
                results.append(result)
            self.last_finished_at = utc_now_iso()
            self.last_results = results
            ok = sum(1 for item in results if item.ok)
            changed = sum(1 for item in results if item.changed)
            quiet = sum(1 for item in results if item.ignored_only)
            errors = len(results) - ok
            LOGGER.info(
                "%-7s | %-32s | ok=%s/%s, changed=%s, quiet=%s, errors=%s | %4d ms",
                "DONE",
                only_slug or "all",
                ok,
                len(results),
                changed,
                quiet,
                errors,
                int((time.perf_counter() - run_started_at) * 1000),
            )
            return results

    async def check_gift(self, slug: str, manual: bool, notify_no_changes: bool) -> CheckResult:
        started_at = time.perf_counter()
        now = datetime.now(timezone.utc)
        if not manual and self.error_backoff_until.get(slug, now) > now:
            until = format_dt(self.error_backoff_until[slug].isoformat(timespec="seconds"), self.tz)
            log_check("BACKOFF", slug, f"skip until {until}", started_at)
            return CheckResult(slug=slug, ok=False, error="backoff after previous error")

        previous = self.store.gift(slug)
        try:
            result = await self.fetcher.fetch(slug, previous)
            if result.not_modified:
                log_check("SKIP", slug, "304 not modified", started_at)
                if manual and notify_no_changes and previous:
                    await self.send_admin_text(f"<b>Без изменений</b>\n{gift_header(previous)}")
                return CheckResult(slug=slug, ok=True, not_modified=True)

            snapshot = result.snapshot
            if snapshot is None:
                raise FetchError("Пустой ответ fetcher")

            if previous is None:
                self.store.upsert_gift(slug, snapshot)
                self.store.append_event({"type": "baseline", "slug": slug, "snapshot": snapshot})
                gift = snapshot.get("gift", {})
                detail = f"baseline | owner={compact_log_value(gift.get('owner_text') or gift.get('owner_address'))}"
                log_check("BASE", slug, detail, started_at)
                if self.config.monitor.notify_initial_snapshot or manual:
                    await self.send_admin_text(format_snapshot_summary(snapshot, self.tz, "Первый снимок NFT-подарка сохранен"))
                return CheckResult(slug=slug, ok=True, baseline=True)

            all_changes, notify_changes = diff_snapshots(previous, snapshot, self.config.monitor.track_image_url)
            self.store.upsert_gift(slug, snapshot)
            if all_changes:
                event_type = "change" if notify_changes else "ignored_change"
                self.store.append_event(
                    {
                        "type": event_type,
                        "slug": slug,
                        "changes": all_changes,
                        "notify_changes": notify_changes,
                        "snapshot": snapshot,
                    }
                )
                if notify_changes:
                    log_check("CHANGE", slug, f"{len(notify_changes)} notify / {len(all_changes)} total changes", started_at)
                    await self.send_admin_text(format_diff(snapshot, notify_changes, self.tz))
                    return CheckResult(slug=slug, ok=True, changed=True)
                log_check("QUIET", slug, f"{len(all_changes)} ignored changes", started_at)
                return CheckResult(slug=slug, ok=True, ignored_only=True)

            if notify_no_changes:
                await self.send_admin_text(
                    f"<b>Без изменений</b>\n{gift_header(snapshot)}\n"
                    f"снимок: <code>{html_escape(format_dt(snapshot.get('taken_at'), self.tz))}</code>"
                )
            status_code = snapshot.get("http", {}).get("status_code")
            page_status = snapshot.get("page_status")
            log_check("OK", slug, f"HTTP {status_code} | {page_status}", started_at)
            return CheckResult(slug=slug, ok=True)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            log_check("ERROR", slug, error, started_at)
            LOGGER.debug("Traceback for %s", slug, exc_info=True)
            self.last_error = error
            if self.config.monitor.error_backoff_seconds:
                self.error_backoff_until[slug] = now + timedelta(seconds=self.config.monitor.error_backoff_seconds)
            self.store.append_event({"type": "error", "slug": slug, "error": error})
            if manual or self.config.monitor.notify_errors:
                await self.send_admin_text(f"<b>Ошибка проверки NFT-подарка</b>\n{gift_link(slug)}\n<code>{html_escape(error)}</code>")
            return CheckResult(slug=slug, ok=False, error=error)

    async def send_admin_text(self, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
        chunks = split_message(text)
        for index, chunk in enumerate(chunks):
            for admin_id in self.config.bot.admin_ids:
                try:
                    await self.bot.send_message(
                        admin_id,
                        chunk,
                        disable_web_page_preview=False,
                        reply_markup=reply_markup if index == len(chunks) - 1 else None,
                    )
                except TelegramAPIError:
                    logging.exception("Failed to send message to admin %s", admin_id)


def gift_link(slug: str) -> str:
    return f'<a href="{html_attr(gift_url(slug))}">{html_escape(slug)}</a>'


def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Статус", callback_data="ngm:status"),
                InlineKeyboardButton(text="Проверить сейчас", callback_data="ngm:check"),
            ],
            [
                InlineKeyboardButton(text="Подарки", callback_data="ngm:gifts"),
                InlineKeyboardButton(text="Помощь", callback_data="ngm:help"),
            ],
        ]
    )


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
        "Ссылка строится как <code>https://t.me/nft/ExampleGift-12345</code>."
    )


def is_admin(config: AppConfig, message_or_query: Message | CallbackQuery) -> bool:
    user = message_or_query.from_user
    return bool(user and user.id in config.bot.admin_ids)


def command_args(message: Message) -> str:
    text = message.text or ""
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def build_router(monitor: GiftMonitor, config: AppConfig) -> Router:
    router = Router()

    @router.message(CommandStart())
    async def on_start(message: Message) -> None:
        if not is_admin(config, message):
            await message.answer("Нет доступа.")
            return
        await message.answer(help_text(), reply_markup=main_keyboard())

    @router.message(Command("help"))
    async def on_help(message: Message) -> None:
        if not is_admin(config, message):
            await message.answer("Нет доступа.")
            return
        await message.answer(help_text(), reply_markup=main_keyboard())

    @router.message(Command("status"))
    async def on_status(message: Message) -> None:
        if not is_admin(config, message):
            await message.answer("Нет доступа.")
            return
        await message.answer(monitor.status_text(), reply_markup=main_keyboard())

    @router.message(Command("gifts"))
    async def on_gifts(message: Message) -> None:
        if not is_admin(config, message):
            await message.answer("Нет доступа.")
            return
        await message.answer(monitor.gifts_text(), reply_markup=main_keyboard())

    @router.message(Command("snapshot"))
    async def on_snapshot(message: Message) -> None:
        if not is_admin(config, message):
            await message.answer("Нет доступа.")
            return
        slug = normalize_slug(command_args(message))
        if not slug:
            await message.answer("Укажи подарок: <code>/snapshot ExampleGift-12345</code>")
            return
        snapshot = monitor.store.gift(slug)
        if snapshot is None:
            await message.answer("В state пока нет снимка для этого подарка. Запусти <code>/check ExampleGift-12345</code>.")
            return
        await message.answer(format_snapshot_summary(snapshot, monitor.tz), reply_markup=main_keyboard())

    @router.message(Command("check"))
    async def on_check(message: Message) -> None:
        if not is_admin(config, message):
            await message.answer("Нет доступа.")
            return
        args = command_args(message)
        slug = normalize_slug(args) if args else None
        if args and not slug:
            await message.answer("Не понял slug. Пример: <code>/check ExampleGift-12345</code>")
            return
        status = await message.answer("Проверяю NFT-подарки...")
        results = await monitor.run_once(manual=True, notify_no_changes=True, only_slug=slug)
        try:
            await status.edit_text(format_results(results), reply_markup=main_keyboard())
        except TelegramBadRequest:
            await message.answer(format_results(results), reply_markup=main_keyboard())

    @router.callback_query(F.data == "ngm:status")
    async def cb_status(query: CallbackQuery) -> None:
        if not is_admin(config, query):
            await query.answer("Нет доступа.", show_alert=True)
            return
        await query.answer()
        await query.message.edit_text(monitor.status_text(), reply_markup=main_keyboard())

    @router.callback_query(F.data == "ngm:gifts")
    async def cb_gifts(query: CallbackQuery) -> None:
        if not is_admin(config, query):
            await query.answer("Нет доступа.", show_alert=True)
            return
        await query.answer()
        await query.message.edit_text(monitor.gifts_text(), reply_markup=main_keyboard())

    @router.callback_query(F.data == "ngm:help")
    async def cb_help(query: CallbackQuery) -> None:
        if not is_admin(config, query):
            await query.answer("Нет доступа.", show_alert=True)
            return
        await query.answer()
        await query.message.edit_text(help_text(), reply_markup=main_keyboard())

    @router.callback_query(F.data == "ngm:check")
    async def cb_check(query: CallbackQuery) -> None:
        if not is_admin(config, query):
            await query.answer("Нет доступа.", show_alert=True)
            return
        await query.answer("Запускаю проверку.")
        if query.message:
            await query.message.edit_text("Проверяю NFT-подарки...", reply_markup=main_keyboard())
        results = await monitor.run_once(manual=True, notify_no_changes=True)
        if query.message:
            await query.message.edit_text(format_results(results), reply_markup=main_keyboard())

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


async def main() -> None:
    config = load_config()
    ensure_dirs(config)
    setup_logging(config)

    store = StateStore(config.monitor.state_path, config.monitor.events_path)
    fetcher = GiftFetcher(config.monitor)
    bot = Bot(config.bot.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    monitor = GiftMonitor(config, store, fetcher, bot)
    dp = Dispatcher()
    dp.include_router(build_router(monitor, config))

    monitor_task = asyncio.create_task(monitor.run_loop())
    try:
        await set_bot_commands(bot)
        await dp.start_polling(bot)
    finally:
        monitor.stop()
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass
        await fetcher.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ConfigError as exc:
        print(f"[CONFIG] {exc}", file=sys.stderr)
        sys.exit(1)
