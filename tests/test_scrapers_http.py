import httpx
import pytest

from scrapers.common.http import Blocked, FetchError, NotFound
from tests.conftest import fixture_text, polite


def test_403_is_blocked_without_retry_and_has_browser_ua():
    c, rec = polite(lambda r: httpx.Response(403, text="nope"))
    with pytest.raises(Blocked):
        c.get("https://example.test/x")
    assert len(rec.requests) == 1
    assert "Mozilla/5.0" in rec.requests[0].headers["user-agent"]


def test_429_backs_off_exponentially_then_blocks():
    sleeps: list[float] = []
    c, rec = polite(lambda r: httpx.Response(429, text="slow"), sleeps, max_retries=2, min_delay=0, max_delay=0)
    with pytest.raises(Blocked):
        c.get("https://example.test/x")
    assert len(rec.requests) == 3
    assert len(sleeps) == 2 and 2 <= sleeps[0] < 3.01 and 4 <= sleeps[1] < 5.01


def test_5xx_retries_then_succeeds():
    seq = iter([httpx.Response(503), httpx.Response(200, json={"ok": 1})])
    c, rec = polite(lambda r: next(seq))
    assert c.get_json("https://example.test/x") == {"ok": 1}
    assert len(rec.requests) == 2


def test_5xx_exhausted_is_fetch_error_not_blocked():
    c, _ = polite(lambda r: httpx.Response(502), max_retries=1)
    with pytest.raises(FetchError) as e:
        c.get("https://example.test/x")
    assert not isinstance(e.value, Blocked)


def test_404_is_notfound():
    c, _ = polite(lambda r: httpx.Response(404))
    with pytest.raises(NotFound):
        c.get("https://example.test/x")


def test_cloudflare_block_page_fixture_raises_blocked_even_on_200():
    html = fixture_text("grailed_blocked.html")
    c, _ = polite(lambda r: httpx.Response(200, text=html, headers={"content-type": "text/html"}))
    with pytest.raises(Blocked):
        c.get("https://www.grailed.test/")


def test_just_a_moment_challenge_is_blocked():
    c, _ = polite(lambda r: httpx.Response(200, text="<html><title>Just a moment...</title></html>",
                                           headers={"content-type": "text/html"}))
    with pytest.raises(Blocked):
        c.get("https://www.mercari.test/")


def test_json_body_mentioning_challenge_words_is_fine():
    c, _ = polite(lambda r: httpx.Response(200, json={"title": "Just a moment... jacket"}))
    assert c.get_json("https://example.test/x")["title"].startswith("Just")


def test_per_host_delay_is_jittered_within_1_to_3_seconds():
    clock = [0.0]
    sleeps: list[float] = []

    def sleep(s):
        sleeps.append(s)
        clock[0] += s

    c, _ = polite(lambda r: httpx.Response(200, json={}), sleeps, monotonic=lambda: clock[0])
    c._sleep = sleep
    for _ in range(6):
        c.get("https://a.test/x")
    assert len(sleeps) == 5 and all(1.0 <= s <= 3.0 for s in sleeps) and len(set(round(s, 3) for s in sleeps)) > 1
    sleeps.clear()
    c.get("https://b.test/x")          # a different host is not delayed
    assert sleeps == []
