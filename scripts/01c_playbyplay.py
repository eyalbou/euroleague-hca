"""Phase 4b -- Play-by-play ingestion (live endpoint per game).

Pulls full event stream for every played game in fact_game and writes
data/bronze/fact_game_event (one row per event, partitioned by season).

Usage:
    python scripts/01c_playbyplay.py                  # all seasons
    python scripts/01c_playbyplay.py --season 2024    # smoke
    python scripts/01c_playbyplay.py --sample 30      # first 30 games only (fast smoke)

Idempotent: per-game json.gz cache; re-runs skip already-fetched games.
"""
# %% imports
from __future__ import annotations

import argparse
import logging
import time

import pandas as pd

from euroleague_hca.ingest import live
from euroleague_hca.warehouse import query

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("01c_playbyplay")


# %% main
def run(season: int | None = None, sample: int | None = None) -> None:
    sql = "SELECT * FROM fact_game"
    if season is not None:
        sql += f" WHERE season = {int(season)}"
    sql += " ORDER BY season, date, game_id"
    games = query(sql)
    if sample:
        games = games.head(int(sample))
    log.info("pulling play-by-play for %d games (season=%s, sample=%s)",
             len(games), season or "all", sample or "none")

    t0 = time.time()
    pbp = live.pull_playbyplay(games, log_every=50)
    elapsed = time.time() - t0
    log.info("pulled %d events in %.1fs (%.2fs/game)",
             len(pbp), elapsed, elapsed / max(len(games), 1))

    if pbp.empty:
        log.error("no pbp rows; aborting bronze write")
        return

    rows = live.write_pbp_bronze(pbp)
    log.info("bronze fact_game_event rows: %d", rows)

    # -- QA block ---------------------------------------------------------
    per_season = pbp.groupby("season").size()
    log.info("events per season: %s", per_season.to_dict())

    per_game = pbp.groupby(["season", "game_id"]).size()
    log.info("events per game: mean=%.0f min=%d median=%d max=%d",
             per_game.mean(), per_game.min(), per_game.median(), per_game.max())

    hist = pbp["action_type"].value_counts()
    log.info("distinct action codes: %d", len(hist))
    log.info("top 20 action codes:\n%s", hist.head(20).to_string())

    null_team_rate = pbp["code_team"].isna().mean()
    log.info("code_team NULL rate: %.3f (expect <= 0.03: BP/EP/TOUT rows)", null_team_rate)

    acting = pbp[pbp["is_home"].notna()]
    home_share = acting["is_home"].mean() if len(acting) else float("nan")
    log.info("is_home mean among acting events: %.3f (expect ~0.50)", home_share)

    # Monotonic event_idx per game (assertion, not just log)
    mono = pbp.groupby(["season", "game_id"])["event_idx"].apply(
        lambda s: bool((s.diff().dropna() == 1).all())
    )
    bad = mono[~mono]
    if len(bad):
        log.error("event_idx NOT monotonic for %d games: %s", len(bad), bad.index.tolist()[:5])
    else:
        log.info("event_idx monotonic for all %d games", len(mono))

    # Sanity: P(AS | 2FGM) on raw next-event (Q0) should be > 0.20 within the same team.
    # We compute it here as a quick smell test.
    ordered = pbp.sort_values(["season", "game_id", "event_idx"])
    ordered["next_action"] = ordered.groupby(["season", "game_id"])["action_type"].shift(-1)
    ordered["next_team"] = ordered.groupby(["season", "game_id"])["code_team"].shift(-1)
    made2 = ordered[(ordered["action_type"] == "2FGM") & (ordered["code_team"].notna())].copy()
    made2_same = made2[made2["next_team"] == made2["code_team"]]
    if len(made2_same):
        as_rate = (made2_same["next_action"] == "AS").mean()
        log.info("sanity: P(AS immediately after 2FGM, same team) = %.3f (expect ~0.40-0.55)", as_rate)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=None)
    ap.add_argument("--sample", type=int, default=None, help="Limit to first N games")
    args = ap.parse_args()
    run(season=args.season, sample=args.sample)
