"""Phase J -- pre-compute per-team x per-season slices for the Team Explorer.

Outputs a single JSON (reports/team_explorer.json) small enough to ship to the
browser for fully-interactive filtering. The filter axes are:
  - team_id (multi-select)
  - season (multi-select)
  - is_home (overlaid)

The JSON is organized for fast client-side filter + aggregation:

  {
    "meta": {"seasons": [...], "teams": [{team_id, name, country, country_iso, n_games}]},
    "team_season": [
      {team_id, season, is_home, n, wins, pts, opp_pts, margin},
      ...
    ],  # one row per (team, season, is_home)  ->  360 rows
    "per_season_league": [
      {season, n_games, home_win_p, mean_home_margin, mean_home_pts, mean_away_pts, attendance_mean}
    ]
  }
"""
from __future__ import annotations

import json
import logging

import pandas as pd

from euroleague_hca import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("27_team_explorer_data")

SILVER = config.SILVER_DIR
OUT = config.REPORTS_DIR / "team_explorer.json"


def main() -> None:
    games = pd.read_parquet(SILVER / "fact_game.parquet")
    games = games[~games["is_neutral"]].copy()
    stats = pd.read_parquet(SILVER / "fact_game_team_stats.parquet")
    stats = stats[~stats["is_neutral"]].copy()
    dim = pd.read_parquet(SILVER / "dim_team.parquet")

    # --- Per (team, season, is_home) aggregation
    g = stats.groupby(["team_id", "season", "is_home"]).agg(
        n=("game_id", "count"),
        wins=("team_win", "sum"),
        pts=("team_pts", "sum"),
        opp_pts=("opp_pts", "sum"),
        fga=("fga", "sum"),
        fgm=("fgm", "sum"),
        fga3=("fga3", "sum"),
        fgm3=("fgm3", "sum"),
        fta=("fta", "sum"),
        ftm=("ftm", "sum"),
        oreb=("oreb", "sum"),
        dreb=("dreb", "sum"),
        tov=("tov", "sum"),
        pf=("pf", "sum"),
        possessions=("possessions", "sum"),
    ).reset_index()
    g["wins"] = g["wins"].astype(int)
    g["margin"] = g["pts"] - g["opp_pts"]
    log.info("per (team, season, is_home) rows: %d", len(g))

    # --- Team dimension, scoped to teams that actually played
    active_teams = sorted(g["team_id"].unique())
    dim_active = dim[dim["team_id"].isin(active_teams)].copy()
    team_to_games = g.groupby("team_id")["n"].sum().to_dict()
    team_meta = []
    for tid in active_teams:
        row = dim_active[dim_active["team_id"] == tid]
        if len(row):
            r = row.iloc[0]
            team_meta.append({
                "team_id": tid,
                "name": r["name_current"] if pd.notna(r["name_current"]) else tid,
                "city": r["city"] if pd.notna(r.get("city")) else None,
                "country": r["country"] if pd.notna(r.get("country")) else None,
                "n_games": int(team_to_games.get(tid, 0)),
            })
        else:
            team_meta.append({"team_id": tid, "name": tid, "n_games": int(team_to_games.get(tid, 0))})
    # Sort by total games (most active first), then alpha
    team_meta.sort(key=lambda x: (-x["n_games"], x["team_id"]))

    # --- Per-season league baselines
    per_season = games.groupby("season").agg(
        n_games=("home_margin", "count"),
        home_win_p=("home_win", "mean"),
        mean_home_margin=("home_margin", "mean"),
        mean_home_pts=("home_pts", "mean"),
        mean_away_pts=("away_pts", "mean"),
        attendance_mean=("attendance", "mean"),
    ).reset_index()

    # --- Pack
    ts_rows = []
    for _, r in g.iterrows():
        ts_rows.append({
            "team_id": r["team_id"],
            "season": int(r["season"]),
            "is_home": int(r["is_home"]),
            "n": int(r["n"]),
            "wins": int(r["wins"]),
            "pts": int(r["pts"]),
            "opp_pts": int(r["opp_pts"]),
            "margin": int(r["margin"]),
            "fga": int(r["fga"]), "fgm": int(r["fgm"]),
            "fga3": int(r["fga3"]), "fgm3": int(r["fgm3"]),
            "fta": int(r["fta"]), "ftm": int(r["ftm"]),
            "oreb": int(r["oreb"]), "dreb": int(r["dreb"]),
            "tov": int(r["tov"]), "pf": int(r["pf"]),
            "possessions": round(float(r["possessions"]), 2) if pd.notna(r["possessions"]) else None,
        })

    ps_rows = []
    for _, r in per_season.iterrows():
        ps_rows.append({
            "season": int(r["season"]),
            "n_games": int(r["n_games"]),
            "home_win_p": round(float(r["home_win_p"]), 4),
            "mean_home_margin": round(float(r["mean_home_margin"]), 3),
            "mean_home_pts": round(float(r["mean_home_pts"]), 2),
            "mean_away_pts": round(float(r["mean_away_pts"]), 2),
            "attendance_mean": round(float(r["attendance_mean"]), 0),
        })

    payload = {
        "meta": {
            "seasons": sorted(games["season"].unique().tolist()),
            "teams": team_meta,
            "n_games": int(len(games)),
            "built_by": "scripts/27_team_explorer_data.py",
        },
        "team_season": ts_rows,
        "per_season_league": ps_rows,
    }
    OUT.write_text(json.dumps(payload, indent=2))
    log.info("wrote %s (%.1f KB, %d teams, %d rows)", OUT, OUT.stat().st_size / 1024,
             len(team_meta), len(ts_rows))


if __name__ == "__main__":
    main()
