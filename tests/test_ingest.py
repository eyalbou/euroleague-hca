"""Invariants on the ingest + silver layer outputs."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SILVER = REPO_ROOT / "data" / "E" / "silver"
BRONZE = REPO_ROOT / "data" / "E" / "bronze"


@pytest.fixture(scope="module")
def fact_game():
    p = SILVER / "fact_game.parquet"
    assert p.exists(), f"missing {p}"
    return pd.read_parquet(p)


@pytest.fixture(scope="module")
def fact_game_event():
    p = SILVER / "fact_game_event.parquet"
    assert p.exists(), f"missing {p}"
    return pd.read_parquet(p)


# 1. fact_game spans exactly the 10 target seasons.
def test_fact_game_seasons(fact_game):
    seasons = sorted(fact_game["season"].unique())
    assert seasons == list(range(2015, 2025)), seasons
    assert len(fact_game) > 2_000, "fewer than ~2k games -- regression"


# 2. Every row has a game_id and both team codes.
def test_fact_game_keys(fact_game):
    for col in ["game_id", "home_team_id", "away_team_id", "season"]:
        assert fact_game[col].notna().all(), f"nulls in {col}"


# 3. fact_game_event events are sorted by event_idx per game (monotonic).
def test_event_idx_monotonic(fact_game_event):
    grp = fact_game_event.sort_values(["season", "game_id", "event_idx"]).groupby(["season", "game_id"])
    for (_s, _g), sub in grp.head(50_000).groupby(["season", "game_id"]):
        assert sub["event_idx"].is_monotonic_increasing, (_s, _g)


# 4. is_home is derivable for the vast majority of events.
def test_is_home_coverage(fact_game_event):
    valid = fact_game_event["is_home"].isin([0, 1]).sum()
    total = len(fact_game_event)
    assert valid / total > 0.95, f"is_home coverage too low: {valid/total:.3f}"
