"""Config and taxonomy file loading."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TAXONOMY_DIR = ROOT / "data" / "taxonomy"
CONFIG_DIR = ROOT / "config"


@lru_cache(maxsize=None)
def load_yaml(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def settings() -> dict:
    return load_yaml(str(CONFIG_DIR / "settings.yaml"))


def sources_config() -> dict[str, dict]:
    return {s["id"]: s for s in load_yaml(str(CONFIG_DIR / "sources.yaml")).get("sources", [])}


def japan_costs() -> dict:
    return load_yaml(str(CONFIG_DIR / "japan_costs.yaml"))
