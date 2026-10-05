from __future__ import annotations

import re
from typing import Any

DIFF_FIELDS = (
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
)

# Эти изменения попадают в state, но не вызывают уведомление.
QUIET_FIELDS = frozenset(
    {
        "quantity_text",
        "issued_count",
        "total_count",
        "original_sender",
        "original_sender_url",
        "original_recipient",
        "original_date",
        "original_footer",
        "owner_photo_url",
    }
)

# Если изменились только они, отдельное событие в JSONL не пишется.
NO_EVENT_FIELDS = frozenset({"quantity_text", "issued_count", "total_count"})

_SLUG_DERIVED_FIELDS = frozenset({"title", "collection", "number"})


def diff_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    gift = snapshot.get("gift", {})
    payload = {field: gift.get(field) for field in DIFF_FIELDS}
    payload["page_status"] = snapshot.get("page_status")
    return payload


def _split_collection(value: str) -> str:
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value)
    text = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", text)
    return " ".join(text.split())


def _slug_metadata(slug: Any) -> dict[str, Any] | None:
    match = re.fullmatch(r"([A-Za-z0-9]+)-(\d+)", str(slug or ""))
    if not match:
        return None
    raw_collection, number = match.group(1), int(match.group(2))
    collection = _split_collection(raw_collection)
    return {
        "slug_title": f"{raw_collection}-{number}",
        "title": f"{collection} #{number}",
        "collection": collection,
        "number": number,
    }


def _matches_slug_metadata(field: str, value: Any, metadata: dict[str, Any]) -> bool:
    if field == "title":
        return " ".join(str(value or "").split()) in {metadata["slug_title"], metadata["title"]}
    if field == "collection":
        return value in (None, "", metadata["collection"])
    return value in (None, "", metadata["number"], str(metadata["number"]))  # number


def _is_slug_metadata_noise(change: dict[str, Any], old: dict[str, Any], new: dict[str, Any]) -> bool:
    """Страница то отдаёт название из slug (до загрузки данных), то настоящее — это не изменение."""
    field = change["field"]
    if field not in _SLUG_DERIVED_FIELDS:
        return False
    metadata = _slug_metadata(new.get("slug") or old.get("slug"))
    return metadata is not None and all(
        _matches_slug_metadata(field, change[side], metadata) for side in ("old", "new")
    )


def diff_snapshots(
    old: dict[str, Any], new: dict[str, Any], track_image_url: bool
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Возвращает (все изменения, изменения для уведомления)."""
    old_payload, new_payload = diff_payload(old), diff_payload(new)
    all_changes = [
        {"field": field, "old": old_payload[field], "new": new_payload[field]}
        for field in sorted(old_payload)
        if old_payload[field] != new_payload[field]
    ]

    quiet = QUIET_FIELDS if track_image_url else QUIET_FIELDS | {"image_url"}
    notify_changes = [
        change
        for change in all_changes
        if change["field"] not in quiet and not _is_slug_metadata_noise(change, old, new)
    ]
    return all_changes, notify_changes


def should_store_change_event(changes: list[dict[str, Any]]) -> bool:
    fields = {change["field"] for change in changes}
    return bool(fields) and not fields <= NO_EVENT_FIELDS
