"""Walk-forward Elo rating with margin-of-victory multiplier and season carry-over.

Key design choices (documented in learning/architecture-decisions/ADR-elo.md):
- HCA NOT baked in: the rating predicts neutral-site outcome. Home advantage is measured from
  the residual after Elo, never hard-coded. This lets downstream models estimate `is_home` as a
  free parameter.
- Season carry-over: at the start of a new season, ratings regress to the mean by 25%
  (carry = 0.75). Teams don't "reset" to 1500, but they don't carry full momentum either.
- Margin-of-victory: FiveThirtyEight NBA Elo's MOV multiplier formula adapted for basketball.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np
import pandas as pd

DEFAULT_START = 1500.0
DEFAULT_K = 20.0
SEASON_CARRY = 0.75


def _expected(r_home: float, r_away: float) -> float:
    return 1.0 / (1.0 + 10 ** ((r_away - r_home) / 400))


def _mov_multiplier(margin: int, rating_diff: float) -> float:
    # 538-style MOV multiplier -- prevents blowouts dominating.
    return np.log(abs(margin) + 1) * (2.2 / ((rating_diff * 0.001) + 2.2))


def walk_forward(fact_game: pd.DataFrame, k: float = DEFAULT_K, start: float = DEFAULT_START) -> pd.DataFrame:
    """Compute pre-game Elo ratings for each team in every game, season-by-season.

    Input columns: game_id, season, date, home_team_id, away_team_id, home_pts, away_pts.
    Returns the input df with added columns: home_elo_pre, away_elo_pre.
    """
    df = fact_game.sort_values(["date"]).copy()
    ratings: dict[str, float] = defaultdict(lambda: start)
    last_season: dict[str, int] = {}

    home_pre, away_pre = [], []
    for _, row in df.iterrows():
        h, a = row["home_team_id"], row["away_team_id"]
        season = row["season"]

        # Season carry-over: regress to mean on season change
        for team in (h, a):
            if team in last_season and last_season[team] != season:
                ratings[team] = SEASON_CARRY * ratings[team] + (1 - SEASON_CARRY) * start
            last_season[team] = season

        rh, ra = ratings[h], ratings[a]
        home_pre.append(rh)
        away_pre.append(ra)

        # Update ratings AFTER we've recorded the pre-game state
        margin = row["home_pts"] - row["away_pts"]
        actual_h = 1.0 if margin > 0 else 0.0 if margin < 0 else 0.5
        expected_h = _expected(rh, ra)
        mult = _mov_multiplier(margin, rh - ra) if margin != 0 else 1.0
        delta = k * mult * (actual_h - expected_h)
        ratings[h] = rh + delta
        ratings[a] = ra - delta

    df["home_elo_pre"] = home_pre
    df["away_elo_pre"] = away_pre
    return df
