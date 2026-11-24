"""Shared plumbing for the scrapers: run context, result record, raw-response writer."""
from __future__ import annotations

import datetime as dt
import gzip
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.config import ROOT
from core.db import Database
from core.fx import Fx

RAW_DIR = ROOT / "raw"


class RawWriter:
    """Appends raw responses to raw/<source>/<utc-timestamp>.jsonl.gz (gitignored, 7-day CI artifact)."""

    def __init__(self, source: str, base: Path | None = None, enabled: bool = True):
        self.enabled = enabled
        self.path: Path | None = None
        self._fh = None
        if enabled:
            stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            safe = source.replace(":", "_").replace("/", "_")
            self.path = (base or RAW_DIR) / safe / f"{stamp}.jsonl.gz"

    def write(self, url: str, status: int | None, body: Any, **extra: Any) -> None:
        if not self.enabled or self.path is None:
            return
        if self._fh is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = gzip.open(self.path, "at", encoding="utf-8")
        rec = {"t": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "url": url, "status": status,
               **extra, "body": body}
        self._fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")

    def close(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None


@dataclass
class Ctx:
    """Everything a scraper needs from the runner. Tests build one directly."""
    db: Database
    fx: Fx
    dry_run: bool = False
    raw: RawWriter | None = None
    max_queries: int | None = None
    deep: bool = False                 # first-fill mode: allow more pages per query
    log: Any = None

    def rawlog(self, url: str, status: int | None, body: Any, **extra: Any) -> None:
        if self.raw:
            self.raw.write(url, status, body, **extra)


@dataclass
class RunResult:
    source: str
    mode: str = "scrape"
    rung: str | None = None
    queries: int = 0
    requests: int = 0
    seen: int = 0
    inserted: int = 0
    updated: int = 0
    comps: int = 0
    skipped_dry: int = 0
    note: str = ""
    errors: list[str] = field(default_factory=list)

    @property
    def stored(self) -> int:
        return self.inserted + self.comps

    def as_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if v not in (0, "", None, [])}
        d["source"], d["mode"] = self.source, self.mode
        return d
