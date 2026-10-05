from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CheckResult:
    slug: str
    ok: bool
    changed: bool = False
    baseline: bool = False
    not_modified: bool = False
    ignored_only: bool = False
    error: str | None = None
