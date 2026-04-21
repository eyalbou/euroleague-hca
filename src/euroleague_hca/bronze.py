"""Raw -> bronze: convert cached JSON into typed parquet partitioned by season."""
from __future__ import annotations

import gzip
import json
import logging
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from euroleague_hca.config import BRONZE_DIR, RAW_DIR

log = logging.getLogger("bronze")


def _write_partitioned(df: pd.DataFrame, entity: str) -> Path:
    out = BRONZE_DIR / entity
    if out.exists():
        import shutil
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    if "season" in df.columns:
        table = pa.Table.from_pandas(df, preserve_index=False)
        pq.write_to_dataset(table, root_path=str(out), partition_cols=["season"])
    else:
        table = pa.Table.from_pandas(df, preserve_index=False)
        pq.write_table(table, out / "part.parquet")
    return out


def mock_to_bronze() -> dict[str, int]:
    """Convert data/raw/mock/** into data/bronze/**. Idempotent."""
    base = RAW_DIR / "mock"
    if not base.exists():
        log.warning("no raw/mock/ found -- run ingest first")
        return {}

    counts: dict[str, int] = {}

    games_dfs = []
    for season_dir in sorted(base.iterdir()):
        if season_dir.is_dir() and season_dir.name.isdigit():
            fg = season_dir / "fact_game.json.gz"
            if fg.exists():
                with gzip.open(fg, "rt") as f:
                    games_dfs.append(pd.DataFrame(json.load(f)))
    if games_dfs:
        games = pd.concat(games_dfs, ignore_index=True)
        _write_partitioned(games, "fact_game")
        counts["fact_game"] = len(games)

    dim_team_path = base / "dim_team.json.gz"
    if dim_team_path.exists():
        with gzip.open(dim_team_path, "rt") as f:
            dt = pd.DataFrame(json.load(f))
            _write_partitioned(dt, "dim_team")
            counts["dim_team"] = len(dt)
    dim_venue_path = base / "dim_venue_season.json.gz"
    if dim_venue_path.exists():
        with gzip.open(dim_venue_path, "rt") as f:
            dv = pd.DataFrame(json.load(f))
            _write_partitioned(dv, "dim_venue_season")
            counts["dim_venue_season"] = len(dv)

    return counts


def live_to_bronze() -> dict[str, int]:
    """Convert data/raw/live/** into data/bronze/**. Idempotent."""
    base = RAW_DIR / "live"
    if not base.exists():
        log.warning("no raw/live/ found -- run ingest first")
        return {}

    counts: dict[str, int] = {}

    # fact_game
    fact_game = []
    game_dir = base / "game"
    if game_dir.exists():
        for season_dir in sorted(game_dir.iterdir()):
            if season_dir.is_dir() and season_dir.name.isdigit():
                season = int(season_dir.name)
                for f in season_dir.glob("*.json.gz"):
                    with gzip.open(f, "rt") as gz:
                        g = json.load(gz)
                        if not g.get("played", False):
                            continue
                        fact_game.append({
                            "game_id": g.get("gameCode"),
                            "season": season,
                            "phase": g.get("phaseType", {}).get("alias", ""),
                            "phase_code": g.get("phaseType", {}).get("code", ""),
                            "round": g.get("round", 0),
                            "date": g.get("date", ""),
                            "home_team_id": g.get("local", {}).get("club", {}).get("code", ""),
                            "away_team_id": g.get("road", {}).get("club", {}).get("code", ""),
                            "venue_code": g.get("venue", {}).get("code", ""),
                            "home_pts": g.get("local", {}).get("score", 0),
                            "away_pts": g.get("road", {}).get("score", 0),
                            "overtime": len(g.get("local", {}).get("partials", {}).get("extraPeriods", {})) > 0,
                            "attendance": g.get("audience", 0),
                            "attendance_source": "live",
                            "is_neutral": g.get("isNeutralVenue", False),
                            "data_source": "live",
                        })

    if fact_game:
        games_df = pd.DataFrame(fact_game)
        _write_partitioned(games_df, "fact_game")
        counts["fact_game"] = len(games_df)

    # fact_game_team_stats
    fact_game_team_stats = []
    boxscore_dir = base / "boxscore"
    game_dir = base / "game"
    if boxscore_dir.exists() and game_dir.exists():
        for season_dir in sorted(boxscore_dir.iterdir()):
            if season_dir.is_dir() and season_dir.name.isdigit():
                season = int(season_dir.name)
                for f in season_dir.glob("*.json.gz"):
                    # Filename is either hashed or {competition}{season}-{gameCode}.json.gz
                    # If hashed, we can look up the gameCode from the corresponding game metadata file
                    game_code = None
                    home_team_id = None
                    away_team_id = None
                    
                    # Read game metadata to get gameCode and team IDs
                    game_meta_file = game_dir / str(season) / f.name
                    if not game_meta_file.exists():
                        # Try the unhashed name if needed, but it should be the same
                        pass
                        
                    if game_meta_file.exists():
                        with gzip.open(game_meta_file, "rt") as gm_gz:
                            gm = json.load(gm_gz)
                            game_code = gm.get("gameCode")
                            home_team_id = gm.get("local", {}).get("club", {}).get("code", "")
                            away_team_id = gm.get("road", {}).get("club", {}).get("code", "")
                    
                    if not game_code or not home_team_id or not away_team_id:
                        continue
                        
                    with gzip.open(f, "rt") as gz:
                        b = json.load(gz)
                        
                        for side in ["local", "road"]:
                            side_data = b.get(side, {})
                            team_id = home_team_id if side == "local" else away_team_id
                            total = side_data.get("total", {})
                            if not team_id or not total:
                                continue
                                
                            fact_game_team_stats.append({
                                "game_id": game_code,
                                "season": season,
                                "team_id": team_id,
                                "is_home": side == "local",
                                "fgm": total.get("fieldGoalsMadeTotal", 0),
                                "fga": total.get("fieldGoalsAttemptedTotal", 0),
                                "fg3m": total.get("fieldGoalsMade3", 0),
                                "fg3a": total.get("fieldGoalsAttempted3", 0),
                                "ftm": total.get("freeThrowsMade", 0),
                                "fta": total.get("freeThrowsAttempted", 0),
                                "orb": total.get("offensiveRebounds", 0),
                                "drb": total.get("defensiveRebounds", 0),
                                "ast": total.get("assistances", 0),
                                "stl": total.get("steals", 0),
                                "blk": total.get("blocksFavour", 0),
                                "tov": total.get("turnovers", 0),
                                "pf": total.get("foulsCommited", 0),
                            })
                            
    if fact_game_team_stats:
        stats_df = pd.DataFrame(fact_game_team_stats)
        _write_partitioned(stats_df, "fact_game_team_stats")
        counts["fact_game_team_stats"] = len(stats_df)

    # dim_team
    dim_team = []
    clubs_dir = base / "clubs"
    if clubs_dir.exists():
        for season_dir in sorted(clubs_dir.iterdir()):
            for f in season_dir.glob("*.json.gz"):
                with gzip.open(f, "rt") as gz:
                    data = json.load(gz)
                    if isinstance(data, dict) and "data" in data:
                        data = data["data"]
                    for c in data:
                        dim_team.append({
                            "team_id": c.get("code", ""),
                            "name_current": c.get("name", ""),
                            "city": c.get("city", ""),
                            "country": (c.get("country") or {}).get("name", ""),
                            "primary_venue_code": "", # Not easily available in v3 clubs
                            "active_from": 2000,
                            "active_to": 2025
                        })
    if dim_team:
        dt_df = pd.DataFrame(dim_team).drop_duplicates(subset=["team_id"])
        _write_partitioned(dt_df, "dim_team")
        counts["dim_team"] = len(dt_df)

    # dim_venue_season
    dim_venue_season = []
    venues_dir = base / "venues"
    if venues_dir.exists():
        for season_dir in sorted(venues_dir.iterdir()):
            for f in season_dir.glob("*.json.gz"):
                with gzip.open(f, "rt") as gz:
                    data = json.load(gz)
                    if isinstance(data, dict) and "data" in data:
                        data = data["data"]
                    for v in data:
                        # We don't have season-specific venue data from the venues endpoint, 
                        # but we can just duplicate it for all active seasons or leave season=0
                        dim_venue_season.append({
                            "venue_code": v.get("code", ""),
                            "season": 0, # Placeholder
                            "name": v.get("name", ""),
                            "city": v.get("address", ""),
                            "country": "",
                            "capacity": v.get("capacity", 0),
                            "is_shared": False
                        })
                        
    # Also extract venues from games to catch missing ones
    if game_dir.exists():
        for season_dir in sorted(game_dir.iterdir()):
            if season_dir.is_dir() and season_dir.name.isdigit():
                season = int(season_dir.name)
                for f in season_dir.glob("*.json.gz"):
                    with gzip.open(f, "rt") as gz:
                        g = json.load(gz)
                        v = g.get("venue")
                        if v:
                            dim_venue_season.append({
                                "venue_code": v.get("code", ""),
                                "season": 0, # Placeholder
                                "name": v.get("name", ""),
                                "city": v.get("address", ""),
                                "country": "",
                                "capacity": v.get("capacity", 0),
                                "is_shared": False
                            })

    if dim_venue_season:
        dv_df = pd.DataFrame(dim_venue_season).drop_duplicates(subset=["venue_code"])
        _write_partitioned(dv_df, "dim_venue_season")
        counts["dim_venue_season"] = len(dv_df)

    return counts
