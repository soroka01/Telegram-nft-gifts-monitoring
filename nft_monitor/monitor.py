from __future__ import annotations

import asyncio
import logging
import random
import time
from datetime import datetime, timedelta
from typing import Any

from .config import AppConfig
from .diff import diff_snapshots, should_store_change_event
from .fetcher import FetchError, GiftFetcher
from .messages import (
    format_diff,
    format_results,
    format_snapshot_summary,
    format_unchanged,
    gift_header,
)
from .models import CheckResult
from .notifier import Notifier
from .state import StateStore
from .util import (
    code_text,
    compact_text,
    format_dt,
    get_timezone,
    gift_link,
    html_escape,
    parse_iso_datetime,
    utc_now,
    utc_now_iso,
)

LOGGER = logging.getLogger("nft-monitor")

MAX_RETRY_AFTER_SECONDS = 3600


def log_check(status: str, slug: str, detail: str, started_at: float | None = None) -> None:
    elapsed = f" | {int((time.perf_counter() - started_at) * 1000):>4} ms" if started_at is not None else ""
    LOGGER.info("%-7s | %-32s | %s%s", status, slug[:32], detail, elapsed)


def _owner_of(snapshot: dict[str, Any]) -> Any:
    gift = snapshot.get("gift", {})
    return gift.get("owner_text") or gift.get("owner_address")


class GiftMonitor:
    def __init__(self, config: AppConfig, store: StateStore, fetcher: GiftFetcher, notifier: Notifier) -> None:
        self.config = config
        self.cfg = config.monitor
        self.store = store
        self.fetcher = fetcher
        self.notifier = notifier
        self.tz = get_timezone(self.cfg.timezone_name)
        self.lock = asyncio.Lock()
        self.stop_event = asyncio.Event()
        self.last_started_at: str | None = None
        self.last_finished_at: str | None = None
        self.last_error: str | None = None
        self.last_results: list[CheckResult] = []
        self.error_backoff_until: dict[str, datetime] = {}
        self.first_error_at: dict[str, datetime] = {}
        self.stale_error_notified: set[str] = set()

    # --- цикл ----------------------------------------------------------------

    def stop(self) -> None:
        self.stop_event.set()

    async def run_loop(self) -> None:
        await self.notifier.send(self.startup_text(), disable_web_page_preview=True)
        while not self.stop_event.is_set():
            try:
                await self.run_once(manual=False, notify_no_changes=False)
            except Exception as exc:
                LOGGER.exception("LOOP    | failed")
                self.last_error = f"{type(exc).__name__}: {exc}"
                await self.notifier.send(f"<b>Ошибка цикла мониторинга</b>\n{code_text(self.last_error)}")

            timeout = self.cfg.interval_seconds + random.uniform(0, self.cfg.jitter_seconds)
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                pass

    async def run_once(
        self, manual: bool, notify_no_changes: bool, only_slug: str | None = None
    ) -> list[CheckResult]:
        if self.lock.locked():
            return [CheckResult(slug=only_slug or "all", ok=False, error="Проверка уже идет.")]

        targets = [only_slug] if only_slug else self.cfg.targets
        async with self.lock:
            started = time.perf_counter()
            self.last_started_at = utc_now_iso()
            self.last_error = None
            results: list[CheckResult] = []
            for index, slug in enumerate(targets):
                if index and self.cfg.request_delay_seconds:
                    await asyncio.sleep(self.cfg.request_delay_seconds)
                results.append(await self.check_gift(slug, manual=manual, notify_no_changes=notify_no_changes))
            self.last_finished_at = utc_now_iso()
            self.last_results = results

            LOGGER.info(
                "%-7s | %-32s | ok=%s/%s, changed=%s, quiet=%s, errors=%s | %4d ms",
                "DONE",
                only_slug or "all",
                sum(r.ok for r in results),
                len(results),
                sum(r.changed for r in results),
                sum(r.ignored_only for r in results),
                sum(not r.ok for r in results),
                int((time.perf_counter() - started) * 1000),
            )
            return results

    # --- проверка одного подарка ------------------------------------------------

    async def check_gift(self, slug: str, manual: bool, notify_no_changes: bool) -> CheckResult:
        started_at = time.perf_counter()
        now = utc_now()
        if not manual and self.error_backoff_until.get(slug, now) > now:
            until = format_dt(self.error_backoff_until[slug], self.tz)
            log_check("BACKOFF", slug, f"skip until {until}", started_at)
            return CheckResult(slug=slug, ok=False, error="backoff after previous error")

        previous = self.store.gift(slug)
        try:
            fetched = await self.fetcher.fetch(slug, previous)
            if fetched.not_modified:
                log_check("SKIP", slug, "304 not modified", started_at)
                if manual and notify_no_changes and previous:
                    await self.notifier.send(f"<b>Без изменений</b>\n{gift_header(previous)}")
                return CheckResult(slug=slug, ok=True, not_modified=True)
            if fetched.snapshot is None:
                raise FetchError("Пустой ответ fetcher")

            self.first_error_at.pop(slug, None)
            self.stale_error_notified.discard(slug)
            self.error_backoff_until.pop(slug, None)

            if previous is None:
                return await self._on_baseline(slug, fetched.snapshot, manual, started_at)
            return await self._on_update(slug, previous, fetched.snapshot, notify_no_changes, started_at)
        except Exception as exc:
            return await self._on_error(slug, previous, exc, manual, now, started_at)

    async def _on_baseline(self, slug: str, snapshot: dict[str, Any], manual: bool, started_at: float) -> CheckResult:
        self.store.upsert_gift(slug, snapshot)
        self.store.append_event({"type": "baseline", "slug": slug, "snapshot": snapshot})
        log_check("BASE", slug, f"baseline | owner={compact_text(_owner_of(snapshot))}", started_at)
        if self.cfg.notify_initial_snapshot or manual:
            await self.notifier.send(format_snapshot_summary(snapshot, self.tz, "Первый снимок NFT-подарка сохранен"))
        return CheckResult(slug=slug, ok=True, baseline=True)

    async def _on_update(
        self, slug: str, previous: dict[str, Any], snapshot: dict[str, Any], notify_no_changes: bool, started_at: float
    ) -> CheckResult:
        all_changes, notify_changes = diff_snapshots(previous, snapshot, self.cfg.track_image_url)
        self.store.upsert_gift(slug, snapshot)

        if all_changes:
            if should_store_change_event(all_changes):
                self.store.append_event(
                    {
                        "type": "change" if notify_changes else "ignored_change",
                        "slug": slug,
                        "changes": all_changes,
                        "notify_changes": notify_changes,
                        "snapshot": snapshot,
                    }
                )
            if notify_changes:
                log_check("CHANGE", slug, f"{len(notify_changes)} notify / {len(all_changes)} total changes", started_at)
                await self.notifier.send(format_diff(snapshot, notify_changes, self.tz))
                return CheckResult(slug=slug, ok=True, changed=True)
            log_check("QUIET", slug, f"{len(all_changes)} ignored changes", started_at)
            return CheckResult(slug=slug, ok=True, ignored_only=True)

        if notify_no_changes:
            await self.notifier.send(format_unchanged(snapshot, self.tz))
        status_code = snapshot.get("http", {}).get("status_code")
        log_check("OK", slug, f"HTTP {status_code} | {snapshot.get('page_status')}", started_at)
        return CheckResult(slug=slug, ok=True)

    async def _on_error(
        self, slug: str, previous: dict[str, Any] | None, exc: Exception, manual: bool, now: datetime, started_at: float
    ) -> CheckResult:
        error = f"{type(exc).__name__}: {exc}"
        log_check("ERROR", slug, error, started_at)
        LOGGER.debug("Traceback for %s", slug, exc_info=True)
        self.last_error = error

        backoff = float(self.cfg.error_backoff_seconds)
        if isinstance(exc, FetchError) and exc.retry_after:
            backoff = max(backoff, min(exc.retry_after, MAX_RETRY_AFTER_SECONDS))
        if backoff:
            self.error_backoff_until[slug] = now + timedelta(seconds=backoff)

        self.store.append_event({"type": "error", "slug": slug, "error": error})
        if manual or self._should_notify_error(slug, previous, now):
            await self.notifier.send(
                f"<b>Ошибка проверки NFT-подарка</b>\n{gift_link(slug)}\n{code_text(error)}"
            )
        else:
            log_check(
                "MUTE",
                slug,
                f"error notification suppressed until gift is stale for {self.cfg.stale_error_notify_seconds}s",
            )
        return CheckResult(slug=slug, ok=False, error=error)

    def _should_notify_error(self, slug: str, previous: dict[str, Any] | None, now: datetime) -> bool:
        threshold = self.cfg.stale_error_notify_seconds
        if threshold <= 0:
            return self.cfg.notify_errors

        last_success = (previous and parse_iso_datetime(previous.get("taken_at"))) or self.first_error_at.setdefault(slug, now)
        if (now - last_success).total_seconds() < threshold or slug in self.stale_error_notified:
            return False
        self.stale_error_notified.add(slug)
        return self.cfg.notify_errors

    # --- тексты для команд ---------------------------------------------------------

    def startup_text(self) -> str:
        targets = "\n".join(f"• {gift_link(slug)}" for slug in self.cfg.targets)
        return (
            "<b>NFT Gift Monitor запущен</b>\n"
            f"Интервал: <code>{self.cfg.interval_seconds} сек</code>\n"
            f"Подарков: <code>{len(self.cfg.targets)}</code>\n"
            "Тихие поля: <code>кол-во, выпущено, исходный отправитель, исходный получатель</code>\n\n"
            f"{targets}"
        )

    def status_text(self) -> str:
        lines = [
            "<b>Статус NFT Gift Monitor</b>",
            f"Состояние: <b>{'идет проверка' if self.lock.locked() else 'ожидает'}</b>",
            f"Подарков в config: <code>{len(self.cfg.targets)}</code>",
            f"Интервал: <code>{self.cfg.interval_seconds} сек</code>",
            f"Последний старт: <code>{html_escape(format_dt(self.last_started_at, self.tz))}</code>",
            f"Последнее завершение: <code>{html_escape(format_dt(self.last_finished_at, self.tz))}</code>",
            f"State: <code>{html_escape(self.cfg.state_path)}</code>",
            f"Events: <code>{html_escape(self.cfg.events_path)}</code>",
        ]
        if self.last_error:
            lines.append(f"Последняя ошибка: <code>{html_escape(self.last_error)}</code>")
        if self.last_results:
            lines += ["", format_results(self.last_results)]
        return "\n".join(lines)

    def gifts_text(self) -> str:
        lines = ["<b>NFT-подарки из config</b>"]
        for slug in self.cfg.targets:
            snapshot = self.store.gift(slug)
            if snapshot:
                taken = format_dt(snapshot.get("taken_at"), self.tz)
                owner = _owner_of(snapshot) or "нет"
                lines.append(f"• {gift_link(slug)} - владелец {code_text(owner)}, снят <code>{html_escape(taken)}</code>")
            else:
                lines.append(f"• {gift_link(slug)} - <code>пока не снят</code>")
        return "\n".join(lines)
