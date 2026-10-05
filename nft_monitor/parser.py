from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .diff import diff_payload
from .state import SCHEMA_VERSION
from .util import clean_text, gift_url, int_from_spaced, stable_hash, utc_now_iso

BASE_URL = "https://telegram.me/"
_FOOTER_RE = re.compile(r"Gifted by (.*?) to (.*?) on (.*)$")
_QUANTITY_RE = re.compile(r"([\d\s]+)\s*/\s*([\d\s]+)")
_TITLE_RE = re.compile(r"(.+?)\s+#(\d+)$")
_TRAIT_ROWS = {"Model": "model", "Backdrop": "backdrop", "Symbol": "symbol"}


def _meta(soup: BeautifulSoup, key: str, *, clean: bool = False) -> str | None:
    tag = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
    value = tag.get("content") if tag else None
    if value is None:
        return None
    return clean_text(value) if clean else str(value).strip()


def _absolute(url: Any) -> str:
    return urljoin(BASE_URL, str(url))


def parse_trait_cell(cell: Tag) -> tuple[str | None, str | None]:
    mark = cell.find("mark")
    rarity = clean_text(mark.get_text(" ")) if mark else ""
    if mark:
        mark.extract()
    return clean_text(cell.get_text(" ")) or None, rarity or None


def parse_quantity(value: str) -> tuple[str | None, int | None, int | None]:
    text = clean_text(value)
    match = _QUANTITY_RE.search(text)
    if not match:
        return text or None, None, None
    return text, int_from_spaced(match.group(1)), int_from_spaced(match.group(2))


def parse_owner_cell(cell: Tag) -> dict[str, Any]:
    owner: dict[str, Any] = {
        "owner_text": clean_text(cell.get_text(" ")) or None,
        "owner_url": None,
        "owner_address": None,
        "owner_photo_url": None,
    }
    if address := cell.select_one(".tgme_gift_owner_address"):
        owner["owner_address"] = clean_text(address.get_text(" ")) or None
    if link := cell.find("a", href=True):
        owner["owner_url"] = _absolute(link["href"])
    if image := cell.find("img", src=True):
        owner["owner_photo_url"] = _absolute(image["src"])
    return owner


def parse_original_footer(footer: Tag) -> dict[str, Any]:
    data: dict[str, Any] = {
        "original_footer": None,
        "original_sender": None,
        "original_sender_url": None,
        "original_recipient": None,
        "original_date": None,
    }
    text = clean_text(footer.get_text(" "))
    data["original_footer"] = text or None
    if link := footer.find("a", href=True):
        data["original_sender"] = clean_text(link.get_text(" ")) or None
        data["original_sender_url"] = _absolute(link["href"])

    if match := _FOOTER_RE.match(text):
        data["original_sender"] = data["original_sender"] or clean_text(match.group(1)) or None
        data["original_recipient"] = clean_text(match.group(2)) or None
        data["original_date"] = clean_text(match.group(3)) or None
    return data


def parse_title(title: str | None, slug: str) -> tuple[str, str | None, int | None]:
    clean = clean_text(title) or slug
    match = _TITLE_RE.match(clean)
    if not match:
        return clean, None, None
    return clean, clean_text(match.group(1)) or None, int(match.group(2))


def _empty_gift(soup: BeautifulSoup, slug: str) -> dict[str, Any]:
    title, collection, number = parse_title(_meta(soup, "og:title", clean=True), slug)
    gift: dict[str, Any] = {
        "title": title,
        "collection": collection,
        "number": number,
        "image_url": _meta(soup, "og:image"),
        "description": _meta(soup, "og:description"),
        "telegram_app_url": _meta(soup, "al:ios:url") or f"tg://nft?slug={slug}",
        "owner_text": None,
        "owner_url": None,
        "owner_address": None,
        "owner_photo_url": None,
        "quantity_text": None,
        "issued_count": None,
        "total_count": None,
        "original_sender": None,
        "original_sender_url": None,
        "original_recipient": None,
        "original_date": None,
        "original_footer": None,
    }
    for prefix in _TRAIT_ROWS.values():
        gift[f"{prefix}_name"] = None
        gift[f"{prefix}_rarity"] = None
    return gift


def parse_gift_html(
    slug: str,
    content: str,
    status_code: int = 200,
    headers: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Превращает HTML страницы t.me/nft/<slug> в снимок подарка."""
    headers = headers or {}
    soup = BeautifulSoup(content, "html.parser")
    gift = _empty_gift(soup, slug)

    table_found = False
    for row in soup.select("table.tgme_gift_table tr"):
        if footer := row.find("th", class_="footer"):
            gift.update(parse_original_footer(footer))
            continue

        header, cell = row.find("th"), row.find("td")
        key = clean_text(header.get_text(" ")) if header else ""
        if not key or cell is None:
            continue
        table_found = True

        if key == "Owner":
            gift.update(parse_owner_cell(cell))
        elif key in _TRAIT_ROWS:
            prefix = _TRAIT_ROWS[key]
            gift[f"{prefix}_name"], gift[f"{prefix}_rarity"] = parse_trait_cell(cell)
        elif key == "Quantity":
            gift["quantity_text"], gift["issued_count"], gift["total_count"] = parse_quantity(cell.get_text(" "))

    if status_code >= 400:
        page_status = f"http_{status_code}"
    else:
        page_status = "ok" if table_found else "no_gift_table"

    snapshot: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "slug": slug,
        "url": gift_url(slug),
        "taken_at": utc_now_iso(),
        "page_status": page_status,
        "gift": gift,
        "http": {
            "status_code": status_code,
            "etag": headers.get("etag"),
            "last_modified": headers.get("last-modified"),
            "content_hash": hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest(),
        },
    }
    snapshot["digest"] = stable_hash(diff_payload(snapshot))
    return snapshot
