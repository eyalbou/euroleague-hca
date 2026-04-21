"""Thin client over the EuroLeague Swagger API.

We use the direct Swagger calls instead of relying on a third-party wrapper. Keeps the project
self-contained (no hard dependency that may not install on latest Python) and gives us explicit
control over retries + caching.

All responses are cached to `data/raw/{endpoint}/{year}/{key}.json.gz` so reruns are free.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from euroleague_hca.config import EUROLEAGUE_API_V2, EUROLEAGUE_API_V3, RAW_DIR

log = logging.getLogger("ingest.swagger")

_session = requests.Session()
_session.headers.update({"Accept": "application/json", "User-Agent": "euroleague-hca/0.1"})

# Rate limit state
_last_request_time = 0.0
_MIN_REQ_INTERVAL = 0.2  # max 5 req/s

def _wait_for_rate_limit():
    global _last_request_time
    now = time.time()
    elapsed = now - _last_request_time
    if elapsed < _MIN_REQ_INTERVAL:
        time.sleep(_MIN_REQ_INTERVAL - elapsed)
    _last_request_time = time.time()

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((requests.exceptions.RequestException, ValueError))
)
def _get(url: str, params: dict[str, Any] | None = None, timeout: float = 20.0) -> requests.Response:
    _wait_for_rate_limit()
    r = _session.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r

def _cache_path(endpoint: str, season: int, key: str) -> Path:
    p = RAW_DIR / "live" / endpoint.strip("/").replace("/", "_") / str(season) / f"{key}.json.gz"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p

def get_cached(endpoint: str, season: int, key: str, url: str, params: dict[str, Any] | None = None) -> Any | None:
    """Cached HTTP GET. Returns parsed JSON or None if the endpoint failed."""
    cache = _cache_path(endpoint, season, key)
    if cache.exists():
        with gzip.open(cache, "rt") as f:
            return json.load(f)
    try:
        r = _get(url, params=params)
        body = r.json()
    except Exception as e:  # noqa: BLE001
        log.warning("swagger %s failed: %s", url, e)
        return None
    cache.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(cache, "wt") as f:
        json.dump(body, f)
    return body


def list_games(season: int, competition: str = "E") -> list[dict]:
    """List games in a season. v2 /competitions/{code}/seasons/{season}/games."""
    url = f"{EUROLEAGUE_API_V2}/competitions/{competition}/seasons/{competition}{season}/games"
    body = get_cached("games_list", season, f"{competition}{season}", url)
    if not body:
        return []
    return body if isinstance(body, list) else body.get("data", [])


def game_metadata(season: int, game_code: int, competition: str = "E") -> dict | None:
    """Game metadata: teams, venue, referees, attendance."""
    url = f"{EUROLEAGUE_API_V2}/competitions/{competition}/seasons/{competition}{season}/games/{game_code}"
    return get_cached("game", season, f"{competition}{season}-{game_code}", url)


def boxscore(season: int, game_code: int, competition: str = "E") -> dict | None:
    url = f"{EUROLEAGUE_API_V2}/competitions/{competition}/seasons/{competition}{season}/games/{game_code}/stats"
    return get_cached("boxscore", season, f"{competition}{season}-{game_code}", url)


def clubs() -> list[dict]:
    url = f"{EUROLEAGUE_API_V3}/clubs"
    body = get_cached("clubs", 0, "clubs", url)
    return body.get("data", []) if isinstance(body, dict) else (body or [])


def venues() -> list[dict]:
    url = f"{EUROLEAGUE_API_V2}/venues"
    body = get_cached("venues", 0, "venues", url)
    return body.get("data", []) if isinstance(body, dict) else (body or [])


def is_reachable() -> bool:
    """Quick health check -- used by the mock-fallback decision."""
    try:
        r = _session.get(EUROLEAGUE_API_V2 + "/competitions", timeout=5)
        return r.status_code < 500
    except Exception:  # noqa: BLE001
        return False
