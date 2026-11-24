"""A small polite HTTP client.

Read-only, one randomized delay per request to the same host, a normal desktop browser
User-Agent, exponential backoff on 429/5xx. A 403, a 429 that survives its retries, or a
bot-challenge page raises `Blocked`; the caller records it and the source falls to the next
rung of its ladder. Nothing here tries to get around a block (no proxies, no fingerprinting).
"""
from __future__ import annotations

import random
import re
import time
from collections import Counter
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ja;q=0.7",
}

# Text that only appears on bot-challenge / block interstitials.
CHALLENGE_MARKERS = (
    "just a moment...",
    "cf-chl-",
    "challenge-platform",
    "sorry, you have been blocked",
    "attention required! | cloudflare",
    "cf-error-details",
    "verify you are human",
    "px-captcha",
    "access denied",
)


class FetchError(Exception):
    """Transient or unexpected failure after retries (not a block)."""

    def __init__(self, msg: str, status: int | None = None, url: str = ""):
        super().__init__(msg)
        self.status, self.url = status, url


class Blocked(FetchError):
    """403 / 429 / challenge page. Respect it: record it, do not retry past the backoff."""


class Parked(Blocked):
    """The rung is on cooldown after an earlier block and no request was made this run. It must not count
    toward the circuit breaker again: the breaker is for real blocks, not for skipped runs."""


class NotFound(FetchError):
    """404 (or 410)."""


def looks_like_challenge(resp: httpx.Response) -> bool:
    ctype = resp.headers.get("content-type", "")
    if "json" in ctype and not (resp.text[:1] == "<"):
        return False
    text = resp.text
    if len(text) > 60000:  # challenge interstitials are small; real pages are not
        return False
    head = text.lower()
    return any(m in head for m in CHALLENGE_MARKERS)


class PoliteClient:
    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        min_delay: float = 1.0,
        max_delay: float = 3.0,
        max_retries: int = 2,
        backoff_base: float = 2.0,
        backoff_cap: float = 60.0,
        timeout: float = 30.0,
        headers: dict[str, str] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        rng: random.Random | None = None,
        on_response: Callable[[httpx.Response], None] | None = None,
    ):
        self.http = httpx.Client(
            transport=transport, timeout=timeout, follow_redirects=True,
            headers={**DEFAULT_HEADERS, **(headers or {})},
        )  # trust_env stays on: the sandbox proxy is picked up from the environment
        self.min_delay, self.max_delay = min_delay, max_delay
        self.max_retries, self.backoff_base, self.backoff_cap = max_retries, backoff_base, backoff_cap
        self._sleep, self._mono = sleep, monotonic
        self._rng = rng or random.Random()
        self._last: dict[str, float] = {}
        self.requests: Counter[str] = Counter()   # per host, for the live-test budget
        self.on_response = on_response

    # -- pacing -----------------------------------------------------------
    def _pace(self, host: str) -> None:
        last = self._last.get(host)
        if last is not None:
            wait = self._rng.uniform(self.min_delay, self.max_delay) - (self._mono() - last)
            if wait > 0:
                self._sleep(wait)
        self._last[host] = self._mono()

    # -- core -------------------------------------------------------------
    def request(self, method: str, url: str, **kw: Any) -> httpx.Response:
        host = urlsplit(url).netloc
        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self._pace(host)
            self.requests[host] += 1
            try:
                resp = self.http.request(method, url, **kw)
            except httpx.TransportError as e:
                last_err = FetchError(f"transport error: {e!r}", url=url)
            else:
                if self.on_response:
                    self.on_response(resp)
                s = resp.status_code
                if s in (404, 410):
                    raise NotFound(f"{s} {url}", s, url)
                if s == 403:
                    raise Blocked(f"403 {url}", s, url)
                if s == 429 or s >= 500:
                    last_err = (Blocked if s == 429 else FetchError)(f"{s} {url}", s, url)
                    retry_after = resp.headers.get("retry-after", "")
                    if attempt < self.max_retries:
                        delay = float(retry_after) if retry_after.isdigit() else self.backoff_base ** (attempt + 1)
                        self._sleep(min(delay, self.backoff_cap) + self._rng.uniform(0, 1))
                        continue
                    raise last_err
                if s >= 400:
                    raise FetchError(f"{s} {url}", s, url)
                if looks_like_challenge(resp):
                    raise Blocked(f"challenge page at {url}", s, url)
                return resp
            if attempt < self.max_retries:
                self._sleep(min(self.backoff_base ** (attempt + 1), self.backoff_cap) + self._rng.uniform(0, 1))
        assert last_err is not None
        raise last_err

    def get(self, url: str, **kw: Any) -> httpx.Response:
        return self.request("GET", url, **kw)

    def post(self, url: str, **kw: Any) -> httpx.Response:
        return self.request("POST", url, **kw)

    def get_json(self, url: str, **kw: Any) -> Any:
        resp = self.get(url, **kw)
        try:
            return resp.json()
        except ValueError as e:
            raise FetchError(f"invalid JSON from {url}: {e}", resp.status_code, url) from e

    def close(self) -> None:
        self.http.close()


_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def next_data(html: str) -> dict | None:
    """The `__NEXT_DATA__` JSON blob of a Next.js page, or None."""
    import json
    m = _NEXT_DATA.search(html)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except ValueError:
        return None
