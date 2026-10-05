from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .util import normalize_slug

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.json"

_TRUE_VALUES = {"1", "true", "yes", "y", "on", "да"}


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class BotConfig:
    token: str
    admin_ids: frozenset[int]


@dataclass(frozen=True)
class MonitorConfig:
    targets: list[str]
    interval_seconds: int
    request_timeout_seconds: float
    request_delay_seconds: float
    jitter_seconds: float
    error_backoff_seconds: int
    stale_error_notify_seconds: int
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


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Не найден {path}. Скопируй config.example.json в config.json.")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Ошибка JSON в {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: ожидался JSON-объект.")
    return data


def env_or_value(env_name: str, value: Any) -> Any:
    env_value = os.getenv(env_name)
    return env_value if env_value not in (None, "") else value


def parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in _TRUE_VALUES


def parse_number(raw: dict[str, Any], key: str, default: float, cast: Callable[[Any], Any], minimum: float) -> Any:
    try:
        return max(minimum, cast(raw.get(key, default)))
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"monitor.{key}: ожидалось число, получено {raw.get(key)!r}.") from exc


def parse_admin_ids(raw: Any) -> frozenset[int]:
    if raw in (None, ""):
        return frozenset()
    if isinstance(raw, int):
        return frozenset({raw})
    chunks = raw.split(",") if isinstance(raw, str) else raw
    try:
        return frozenset(int(str(item).strip()) for item in chunks if str(item).strip())
    except ValueError as exc:
        raise ConfigError(f"bot.admin_ids: некорректный ID в {raw!r}.") from exc


def parse_targets(raw: Any) -> list[str]:
    values = raw.split(",") if isinstance(raw, str) else (raw or [])

    targets: list[str] = []
    for item in values:
        if isinstance(item, dict):
            if not parse_bool(item.get("enabled"), True):
                continue
            item = item.get("slug") or item.get("target") or item.get("url")
        slug = normalize_slug(item)
        if slug and slug not in targets:
            targets.append(slug)
    return targets


def validate_secret(name: str, value: Any) -> str:
    text = str(value or "").strip()
    if not text or text.startswith(("PUT_", "YOUR_")):
        raise ConfigError(f"Заполни {name} в config.json или через переменную окружения.")
    return text


def resolve_path(raw: Any, default: str) -> Path:
    path = Path(str(raw or default).strip())
    return path if path.is_absolute() else BASE_DIR / path


def load_config(path: Path = CONFIG_PATH) -> AppConfig:
    raw = load_json(path)
    bot_raw = raw.get("bot") or {}
    monitor_raw = raw.get("monitor") or {}

    token = validate_secret("bot.token", env_or_value("BOT_TOKEN", bot_raw.get("token")))
    admin_ids = parse_admin_ids(env_or_value("ADMIN_IDS", bot_raw.get("admin_ids", bot_raw.get("admin_id"))))
    if not admin_ids:
        raise ConfigError("Укажи хотя бы один ID администратора в bot.admin_ids (или ADMIN_IDS).")
    targets = parse_targets(env_or_value("NFT_GIFT_TARGETS", monitor_raw.get("targets", [])))
    if not targets:
        raise ConfigError("Добавь хотя бы один NFT-подарок в monitor.targets, например ExampleGift-12345.")

    monitor = MonitorConfig(
        targets=targets,
        interval_seconds=parse_number(monitor_raw, "interval_seconds", 30, int, 5),
        request_timeout_seconds=parse_number(monitor_raw, "request_timeout_seconds", 10, float, 2.0),
        request_delay_seconds=parse_number(monitor_raw, "request_delay_seconds", 0.25, float, 0.0),
        jitter_seconds=parse_number(monitor_raw, "jitter_seconds", 3, float, 0.0),
        error_backoff_seconds=parse_number(monitor_raw, "error_backoff_seconds", 120, int, 0),
        stale_error_notify_seconds=parse_number(monitor_raw, "stale_error_notify_seconds", 3600, int, 0),
        notify_initial_snapshot=parse_bool(monitor_raw.get("notify_initial_snapshot"), True),
        notify_errors=parse_bool(monitor_raw.get("notify_errors"), True),
        track_image_url=parse_bool(monitor_raw.get("track_image_url"), False),
        timezone_name=str(monitor_raw.get("timezone", "Europe/Moscow")),
        state_path=resolve_path(monitor_raw.get("state_path"), "state/nft_gift_state.json"),
        events_path=resolve_path(monitor_raw.get("events_path"), "logs/nft_gift_events.jsonl"),
        user_agent=str(monitor_raw.get("user_agent") or "Mozilla/5.0"),
    )
    return AppConfig(bot=BotConfig(token=token, admin_ids=admin_ids), monitor=monitor)
