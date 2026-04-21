"""Phase 4 -- Boxscore ingestion (live v2 stats endpoint per game).

Pulls team-total boxscore for every played game in fact_game and writes
data/bronze/fact_game_team_stats. Rows: two per game (home + road).

Usage:
    python scripts/01b_boxscores.py             # all seasons
    python scripts/01b_boxscores.py --season 2024

Idempotent: uses swagger_direct cache, so re-runs skip already-fetched games.
"""
# %% imports
from __future__ import annotations

import argparse
import logging
import time

import pandas as pd

from euroleague_hca import config
from euroleague_hca.ingest import live
from euroleague_hca.warehouse import query

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("01b_boxscores")


# %% main
def run(season: int | None = None) -> None:
    sql = "SELECT * FROM fact_game"
    if season is not None:
        sql += f" WHERE season = {int(season)}"
    games = query(sql)
    log.info("pulling boxscores for %d games (season=%s)", len(games), season or "all")

    t0 = time.time()
    bs_df = live.pull_boxscores(games, log_every=50)
    elapsed = time.time() - t0
    log.info("pulled %d team-game rows in %.1fs (%.2fs/game)",
             len(bs_df), elapsed, elapsed / max(len(games), 1))

    if bs_df.empty:
        log.error("no boxscore rows; aborting bronze write")
        return

    rows = live.write_boxscore_bronze(bs_df)
    log.info("bronze fact_game_team_stats rows: %d", rows)

    # quick QA
    per_season = bs_df.groupby("season").size()
    log.info("per season: %s", per_season.to_dict())

    # mean HCA indicators vs our expectation
    home = bs_df[bs_df["is_home"] == 1]
    away = bs_df[bs_df["is_home"] == 0]
    log.info(
        "home avg: pts=%.1f  efg=%.3f  ts=%.3f  poss=%.1f  pf=%.1f",
        home["points"].mean(), home["efg_pct"].mean(),
        home["ts_pct"].mean(), home["possessions"].mean(), home["pf"].mean(),
    )
    log.info(
        "away avg: pts=%.1f  efg=%.3f  ts=%.3f  poss=%.1f  pf=%.1f",
        away["points"].mean(), away["efg_pct"].mean(),
        away["ts_pct"].mean(), away["possessions"].mean(), away["pf"].mean(),
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=None)
    args = ap.parse_args()
    run(season=args.season)
