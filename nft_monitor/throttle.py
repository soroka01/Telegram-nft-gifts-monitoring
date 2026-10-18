from __future__ import annotations

import asyncio
import time
from datetime import datetime

from .util import utc_now

BURST_REQUESTS = 15


class RequestPacer:
    """Держит средний темп запросов не выше `requests_per_hour`; после простоя пропускает короткую очередь без пауз."""

    def __init__(self, requests_per_hour: float, burst: int = BURST_REQUESTS) -> None:
        self.rate = requests_per_hour / 3600 if requests_per_hour > 0 else 0.0  # запросов в секунду
        self.burst = float(max(1, burst))
        self._tokens = self.burst
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        if not self.rate:
            return
        async with self._lock:
            now = time.monotonic()
            self._tokens = min(self.burst, self._tokens + (now - self._updated) * self.rate)
            self._updated = now
            if self._tokens < 1:
                await asyncio.sleep((1 - self._tokens) / self.rate)
                self._tokens, self._updated = 1.0, time.monotonic()
            self._tokens -= 1


class ThrottleGuard:
    """Замечает, что Telegram перестал отдавать данные подарков, и ставит мониторинг на паузу.

    Пауза удваивается после каждой неудачной пробы и снимается первым нормальным ответом.
    """

    def __init__(self, trigger: int = 3, base_seconds: float = 60, max_seconds: float = 600) -> None:
        self.trigger = max(1, trigger)
        self.base_seconds = base_seconds
        self.max_seconds = max_seconds
        self.streak = 0  # страниц без данных подряд
        self.pause_seconds = 0.0  # длина текущей паузы; 0 — ограничения нет
        self.since: datetime | None = None
        self._until = 0.0

    @property
    def active(self) -> bool:
        return self.pause_seconds > 0

    def remaining(self) -> float:
        return max(0.0, self._until - time.monotonic())

    def on_page(self) -> bool:
        """Пришла нормальная страница. True, если ею снято ограничение."""
        self.streak = 0
        was_active = self.active
        self.pause_seconds, self.since, self._until = 0.0, None, 0.0
        return was_active

    def on_empty(self) -> bool:
        """Пришла страница без данных. True, если ограничение только что включено или продлено."""
        self.streak += 1
        if self.active:
            self.pause_seconds = min(self.pause_seconds * 2, self.max_seconds)
        elif self.streak >= self.trigger:
            self.pause_seconds, self.since = self.base_seconds, utc_now()
        else:
            return False
        self._until = time.monotonic() + self.pause_seconds
        return True
