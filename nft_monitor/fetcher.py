from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from .config import MonitorConfig
from .parser import parse_gift_html
from .util import gift_url

LOGGER = logging.getLogger("nft-monitor")

RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})


class FetchError(RuntimeError):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


@dataclass
class FetchResult:
    snapshot: dict[str, Any] | None
    not_modified: bool = False
    status_code: int | None = None


def _parse_retry_after(value: str | None) -> float | None:
    try:
        return max(0.0, float(value)) if value else None
    except ValueError:  # HTTP-date не поддерживаем
        return None


class GiftFetcher:
    def __init__(self, config: MonitorConfig) -> None:
        self.client = httpx.AsyncClient(
            headers={
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "accept-language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                "cache-control": "no-cache",
                "user-agent": config.user_agent,
            },
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

        try:
            response = await self.client.get(gift_url(slug), headers=headers)
        except httpx.HTTPError as exc:
            raise FetchError(f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__) from exc

        status = response.status_code
        if status == 304:
            return FetchResult(snapshot=None, not_modified=True, status_code=status)
        if status in RETRYABLE_STATUSES:
            retry_after = _parse_retry_after(response.headers.get("retry-after"))
            suffix = f", retry-after {retry_after:g} сек." if retry_after is not None else ""
            raise FetchError(f"HTTP {status}{suffix}", retry_after=retry_after)
        if status >= 400 and status != 404:
            raise FetchError(f"HTTP {status}")

        snapshot = parse_gift_html(slug, response.text, status, response.headers)
        if previous and previous.get("page_status") == "ok" and snapshot["page_status"] == "no_gift_table":
            LOGGER.warning(
                "Skipping transient non-gift page for %s: title=%r", slug, snapshot["gift"].get("title")
            )
            return FetchResult(snapshot=None, not_modified=True, status_code=status)
        return FetchResult(snapshot=snapshot, status_code=status)
