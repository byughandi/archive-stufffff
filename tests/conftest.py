import json
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.db import SqliteDatabase  # noqa: E402
from core.fx import Fx  # noqa: E402
from scrapers.common import Ctx  # noqa: E402
from scrapers.common.http import PoliteClient  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def db(tmp_path):
    d = SqliteDatabase(str(tmp_path / "t.db"))
    d.migrate()
    yield d
    d.close()


@pytest.fixture
def fx():
    return Fx({"USD": 1.0, "JPY": 150.0, "CAD": 1.4, "AUD": 1.5, "EUR": 0.9}, 0, False)


@pytest.fixture
def ctx(db, fx):
    return Ctx(db, fx)


def fixture_text(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def fixture_json(name: str):
    return json.loads(fixture_text(name))


class Recorder:
    """Records calls made through a MockTransport."""
    def __init__(self):
        self.requests: list[httpx.Request] = []

    @property
    def urls(self):
        return [str(r.url) for r in self.requests]


def polite(handler, sleeps=None, **kw) -> tuple[PoliteClient, Recorder]:
    rec = Recorder()

    def wrapped(request: httpx.Request) -> httpx.Response:
        rec.requests.append(request)
        return handler(request)

    sl = sleeps if sleeps is not None else []
    c = PoliteClient(transport=httpx.MockTransport(wrapped), sleep=sl.append, **kw)
    return c, rec
