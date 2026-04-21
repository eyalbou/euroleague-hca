"""Thin client for the EuroLeague *live* host (not the Swagger host).

The Play-by-Play endpoint is not part of the v2/v3 Swagger API -- it lives on
`https://live.euroleague.net/api/PlaybyPlay` and returns events grouped by
quarter plus team identifiers. This module is kept deliberately separate from
`swagger_direct.py` so the distinction is explicit.

All responses are cached to `data/raw/live/playbyplay/{season}/E{season}-{gamecode}.json.gz`
so reruns are free and the cache doubles as a resume checkpoint.
"""
from __future__ import annotations

import gzip
import json
import logging
import time
from pathlib import Path
from typing import Any

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from euroleague_hca.config import RAW_DIR

log = logging.getLogger("ingest.live_direct")

LIVE_API = "https://live.euroleague.net/api"

_session = requests.Session()
_session.headers.update({"Accept": "application/json", "User-Agent": "euroleague-hca/0.1"})

_last_request_time = 0.0
_MIN_REQ_INTERVAL = 0.2  # 5 req/s ceiling, friendly to the live host


def _wait_for_rate_limit() -> None:
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < _MIN_REQ_INTERVAL:
        time.sleep(_MIN_REQ_INTERVAL - elapsed)
    _last_request_time = time.time()


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((requests.exceptions.RequestException, ValueError)),
)
def _get(url: str, params: dict[str, Any] | None = None, timeout: float = 20.0) -> requests.Response:
    _wait_for_rate_limit()
    r = _session.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r


def _cache_path(endpoint: str, season: int, key: str) -> Path:
    p = RAW_DIR / "live" / endpoint / str(season) / f"{key}.json.gz"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def get_cached(endpoint: str, season: int, key: str, url: str,
               params: dict[str, Any] | None = None) -> Any | None:
    """Cached HTTP GET. Returns parsed JSON or None on failure."""
    cache = _cache_path(endpoint, season, key)
    if cache.exists():
        with gzip.open(cache, "rt") as f:
            return json.load(f)
    try:
        r = _get(url, params=params)
        body = r.json()
    except Exception as e:  # noqa: BLE001
        log.warning("live_direct %s failed: %s", url, e)
        return None
    cache.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(cache, "wt") as f:
        json.dump(body, f)
    return body


def play_by_play(season: int, game_code: int, competition: str = "E") -> dict | None:
    """Fetch the raw Play-by-Play document for one game.

    Returns the API response dict with top-level keys:
      CodeTeamA, CodeTeamB, FirstQuarter, SecondQuarter, ThirdQuarter,
      ForthQuarter (API spelling), ExtraTime, Live, ActualQuarter, TeamA, TeamB.

    Event order within each quarter is the array order returned by the API --
    NUMBEROFPLAY is known-unreliable (see giasemidis/euroleague_api).
    """
    url = f"{LIVE_API}/PlaybyPlay"
    params = {"gamecode": game_code, "seasoncode": f"{competition}{season}"}
    key = f"{competition}{season}-{game_code}"
    body = get_cached("playbyplay", season, key, url, params=params)
    return body if isinstance(body, dict) else None


def is_reachable() -> bool:
    """Quick health check -- used by the mock-fallback decision."""
    try:
        r = _session.get(
            f"{LIVE_API}/PlaybyPlay",
            params={"gamecode": 1, "seasoncode": "E2024"},
            timeout=5,
        )
        return r.status_code < 500
    except Exception:  # noqa: BLE001
        return False
