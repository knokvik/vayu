"""Loads the local JSON data files (no network, no database)."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any


def data_dir() -> Path:
    """Directory holding city_profiles.json and services_ranges.json.

    Override with the TREE_LOSS_DATA_DIR environment variable; defaults to the
    repository's top-level ``data/`` folder.
    """
    override = os.environ.get("TREE_LOSS_DATA_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "data"


def _read(name: str) -> dict[str, Any]:
    path = data_dir() / name
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def load_city_profiles() -> dict[str, Any]:
    return _read("city_profiles.json")


@lru_cache(maxsize=1)
def load_services_ranges() -> dict[str, Any]:
    return _read("services_ranges.json")


def clear_cache() -> None:
    load_city_profiles.cache_clear()
    load_services_ranges.cache_clear()
