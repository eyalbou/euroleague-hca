"""Schema + coverage + referential integrity + sanity checks for silver tables."""
from __future__ import annotations

import logging

import pandas as pd

from euroleague_hca.warehouse import query

log = logging.getLogger("validate")


def coverage_by_season() -> pd.DataFrame:
    return query(
        """
        SELECT season,
               COUNT(*) as n_games,
               SUM(home_win) as home_wins,
               ROUND(AVG(home_win) * 100.0, 2) as home_win_pct,
               ROUND(AVG(home_margin), 2) as league_hca_pts,
               SUM(CASE WHEN attendance IS NULL THEN 1 ELSE 0 END) as n_missing_attendance
        FROM fact_game
        GROUP BY season
        ORDER BY season
        """
    )


def referential_integrity() -> dict[str, int]:
    out = {}
    teams = set(query("SELECT team_id FROM dim_team")["team_id"])
    venues = set(query("SELECT venue_code FROM dim_venue_season")["venue_code"])

    games = query("SELECT home_team_id, away_team_id, venue_code FROM fact_game")
    out["games_home_orphan"] = (~games["home_team_id"].isin(teams)).sum()
    out["games_away_orphan"] = (~games["away_team_id"].isin(teams)).sum()
    out["games_venue_orphan"] = (~games["venue_code"].isin(venues)).sum()
    out["games_self_play"] = (games["home_team_id"] == games["away_team_id"]).sum()
    return out


def sanity_checks() -> dict[str, object]:
    cov = coverage_by_season()
    ref = referential_integrity()
    overall = query(
        "SELECT AVG(home_margin) as league_hca, AVG(home_win) as league_home_win_pct, "
        "COUNT(*) as n_games FROM fact_game"
    ).iloc[0]
    return {
        "coverage": cov.to_dict("records"),
        "referential": ref,
        "overall_hca": float(overall["league_hca"]),
        "overall_home_win_pct": float(overall["league_home_win_pct"]),
        "n_games": int(overall["n_games"]),
    }
