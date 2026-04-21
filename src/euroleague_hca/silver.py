"""Bronze -> silver: clean, normalize, deduplicate, join venue capacity from reference."""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from euroleague_hca.config import BRONZE_DIR, REFERENCE_DIR, SILVER_DIR

log = logging.getLogger("silver")


def _read_bronze(entity: str) -> pd.DataFrame:
    p = BRONZE_DIR / entity
    if not p.exists():
        log.warning("bronze/%s missing", entity)
        return pd.DataFrame()
    try:
        return pd.read_parquet(p)
    except Exception:
        # fallback for non-partitioned
        files = list(p.rglob("*.parquet"))
        if not files:
            return pd.DataFrame()
        return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)


def _load_capacity_reference() -> pd.DataFrame:
    path = REFERENCE_DIR / "venue_capacity.csv"
    if path.exists():
        return pd.read_csv(path)
    return pd.DataFrame(columns=["venue_code", "season", "capacity", "source_url", "last_checked"])


def build_silver() -> dict[str, Path]:
    SILVER_DIR.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    # dim_team
    dim_team = _read_bronze("dim_team")
    if not dim_team.empty:
        out = SILVER_DIR / "dim_team.parquet"
        dim_team.to_parquet(out, index=False)
        paths["dim_team"] = out

    # dim_venue_season -- merged with reference override where present
    dim_venue = _read_bronze("dim_venue_season")
    cap_ref = _load_capacity_reference()
    if not dim_venue.empty and not cap_ref.empty:
        dim_venue = dim_venue.merge(
            cap_ref[["venue_code", "season", "capacity"]].rename(columns={"capacity": "capacity_ref"}),
            on=["venue_code", "season"], how="left",
        )
        # Prefer reference value when present
        dim_venue["capacity"] = dim_venue["capacity_ref"].combine_first(dim_venue["capacity"])
        dim_venue = dim_venue.drop(columns=["capacity_ref"])
    if not dim_venue.empty:
        out = SILVER_DIR / "dim_venue_season.parquet"
        dim_venue.to_parquet(out, index=False)
        paths["dim_venue_season"] = out

    # fact_game -- dedupe on (season, game_id); compute home_win / home_margin.
    # NOTE: game_id values (integer game codes) are only unique within a season;
    # we MUST include season in the dedup key or cross-season games collapse.
    fact_game = _read_bronze("fact_game")
    if not fact_game.empty:
        fact_game = fact_game.drop_duplicates(subset=["season", "game_id"]).sort_values(["season", "date"])
        fact_game["home_margin"] = fact_game["home_pts"] - fact_game["away_pts"]
        fact_game["home_win"] = (fact_game["home_margin"] > 0).astype(int)
        fact_game["date"] = pd.to_datetime(fact_game["date"]).dt.date.astype(str)
        out = SILVER_DIR / "fact_game.parquet"
        fact_game.to_parquet(out, index=False)
        paths["fact_game"] = out

    # fact_game_team_stats: derived from fact_game -- one row per (game, team)
    if not fact_game.empty:
        home = fact_game.rename(columns={"home_team_id": "team_id", "away_team_id": "opp_team_id"}).copy()
        home["is_home"] = 1
        home["team_pts"] = home["home_pts"]
        home["opp_pts"] = home["away_pts"]
        away = fact_game.rename(columns={"away_team_id": "team_id", "home_team_id": "opp_team_id"}).copy()
        away["is_home"] = 0
        away["team_pts"] = away["away_pts"]
        away["opp_pts"] = away["home_pts"]
        cols = ["game_id", "season", "phase", "round", "date", "team_id", "opp_team_id",
                "venue_code", "is_home", "team_pts", "opp_pts", "attendance",
                "attendance_source", "is_neutral", "data_source"]
        if "phase_code" in fact_game.columns:
            cols.insert(3, "phase_code")
        fact_gt = pd.concat([home[cols], away[cols]], ignore_index=True)
        fact_gt["point_diff"] = fact_gt["team_pts"] - fact_gt["opp_pts"]
        fact_gt["team_win"] = (fact_gt["point_diff"] > 0).astype(int)

        # Enrich with real boxscore stats when available (Phase 4)
        bronze_stats = _read_bronze("fact_game_team_stats")
        if not bronze_stats.empty and "fga" in bronze_stats.columns:
            bronze_stats = bronze_stats.drop_duplicates(subset=["game_id", "team_id"])
            drop_cols = [c for c in ["season", "is_home"] if c in bronze_stats.columns]
            bronze_stats = bronze_stats.drop(columns=drop_cols)
            fact_gt = fact_gt.merge(bronze_stats, on=["game_id", "team_id"], how="left")
            log.info("silver: enriched %d/%d team-game rows with boxscore stats",
                     int(fact_gt["fga"].notna().sum()), len(fact_gt))

        out = SILVER_DIR / "fact_game_team_stats.parquet"
        fact_gt.to_parquet(out, index=False)
        paths["fact_game_team_stats"] = out

    # fact_game_event: enrich bronze PBP with phase_code + closed_doors + action_group.
    # is_home is already resolved at ingest time (CODETEAM vs CodeTeamA), so we only
    # need to join phase + the crowd flag from fact_game.
    bronze_events = _read_bronze("fact_game_event")
    if not bronze_events.empty and not fact_game.empty:
        join_cols = ["season", "game_id", "phase_code", "attendance"]
        available = [c for c in join_cols if c in fact_game.columns]
        events = bronze_events.merge(
            fact_game[available].drop_duplicates(["season", "game_id"]),
            on=["season", "game_id"], how="left",
        )
        # Closed-doors: attendance == 0 (COVID seasons + a handful of post-COVID residuals).
        if "attendance" in events.columns:
            events["closed_doors"] = (events["attendance"].fillna(-1) == 0).astype(int)
        else:
            events["closed_doors"] = 0

        # Coarse action groups used by the bar-chart rollups.
        GROUP_MAP = {
            "2FGM": "shot_made_2", "3FGM": "shot_made_3", "FTM": "ft_made",
            "2FGA": "shot_miss_2", "3FGA": "shot_miss_3", "FTA": "ft_miss",
            "D": "reb_def", "O": "reb_off",
            "AS": "assist", "TO": "turnover", "ST": "steal",
            "FV": "block_given", "AG": "block_received",
            "CM": "foul_committed", "RV": "foul_drawn",
            "OF": "foul_offensive", "CMU": "foul_unsport",
            "CMT": "foul_technical", "CMD": "foul_disqualifying",
            "IN": "sub_in", "OUT": "sub_out",
            "TOUT": "timeout", "TOUT_TV": "timeout",
            "JB": "clock", "BP": "clock", "EP": "clock", "EG": "clock",
        }
        events["action_group"] = events["action_type"].map(GROUP_MAP).fillna("other")

        # is_action flag: TRUE for in-play events used by Q0/Q1/Q2 Markov computations.
        # Excludes clock events, subs, and timeouts.
        _CLOCK_OR_ADMIN = {"IN", "OUT", "TOUT", "TOUT_TV", "JB", "BP", "EP", "EG", "CCH", "C", "B"}
        events["is_action"] = (~events["action_type"].isin(_CLOCK_OR_ADMIN)).astype(int)

        out = SILVER_DIR / "fact_game_event.parquet"
        events.to_parquet(out, index=False)
        paths["fact_game_event"] = out
        log.info("silver fact_game_event: %d rows (of which %d in-play)",
                 len(events), int(events["is_action"].sum()))

    return paths
