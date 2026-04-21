"""Phase 10b -- NBA context ingestion (official NBA Stats API via nba_api).

Pulls regular-season game logs for the last 10 NBA seasons (2015-16 through 2024-25)
and writes a minimal `fact_game` parquet compatible with the EuroLeague schema used
for the cross-league context panel.

Source: nba_api.stats.endpoints.LeagueGameLog -- wraps stats.nba.com with the
required headers. Regular Season only. No playoffs.

Output: data/NBA/silver/fact_game.parquet
Columns: game_id, season, date, home_team_id, away_team_id, home_pts, away_pts,
         home_margin, phase_code (always 'RS').

Idempotent: caches raw per-season frames in data/NBA/raw/leaguegamelog_<season>.parquet.
Runs the API only for seasons not yet cached.
"""
# %% imports
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

from euroleague_hca import config

# %% config
NBA_ROOT = config.PROJECT_ROOT / "data" / "NBA"
RAW_DIR = NBA_ROOT / "raw"
SILVER_DIR = NBA_ROOT / "silver"
RAW_DIR.mkdir(parents=True, exist_ok=True)
SILVER_DIR.mkdir(parents=True, exist_ok=True)

SEASONS = [
    "2015-16", "2016-17", "2017-18", "2018-19", "2019-20",
    "2020-21", "2021-22", "2022-23", "2023-24", "2024-25",
]


def season_start_year(s: str) -> int:
    return int(s.split("-")[0])


# %% fetch loop
def fetch_season(season: str, retries: int = 3) -> pd.DataFrame:
    """Fetch a full regular-season LeagueGameLog, with retry + caching."""
    cache = RAW_DIR / f"leaguegamelog_{season}.parquet"
    if cache.exists():
        df = pd.read_parquet(cache)
        print(f"  {season}: cached -- {len(df)} team-game rows")
        return df

    from nba_api.stats.endpoints import leaguegamelog

    last_err = None
    for attempt in range(1, retries + 1):
        try:
            lg = leaguegamelog.LeagueGameLog(
                season=season,
                season_type_all_star="Regular Season",
                timeout=90,
            )
            df = lg.get_data_frames()[0]
            df.to_parquet(cache, index=False)
            print(f"  {season}: fetched {len(df)} team-game rows (attempt {attempt})")
            return df
        except Exception as e:
            last_err = e
            print(f"  {season}: attempt {attempt} failed: {e}")
            time.sleep(3 * attempt)
    raise RuntimeError(f"failed to fetch {season}: {last_err}")


def collapse_to_games(tg: pd.DataFrame, season: str) -> pd.DataFrame:
    """Collapse two rows per game (one per team) into one row with home/away."""
    tg = tg.copy()
    tg["is_home"] = tg["MATCHUP"].str.contains(" vs. ").astype(int)
    home = tg[tg["is_home"] == 1][["GAME_ID", "GAME_DATE", "TEAM_ID", "TEAM_ABBREVIATION", "PTS"]].rename(
        columns={"TEAM_ID": "home_team_id", "TEAM_ABBREVIATION": "home_tla", "PTS": "home_pts"})
    away = tg[tg["is_home"] == 0][["GAME_ID", "TEAM_ID", "TEAM_ABBREVIATION", "PTS"]].rename(
        columns={"TEAM_ID": "away_team_id", "TEAM_ABBREVIATION": "away_tla", "PTS": "away_pts"})
    g = home.merge(away, on="GAME_ID")
    g = g.rename(columns={"GAME_ID": "game_id", "GAME_DATE": "date"})
    g["date"] = pd.to_datetime(g["date"])
    g["season"] = season_start_year(season)
    g["phase_code"] = "RS"
    g["home_margin"] = g["home_pts"].astype(int) - g["away_pts"].astype(int)
    return g[["game_id", "season", "date", "home_team_id", "home_tla",
              "away_team_id", "away_tla", "home_pts", "away_pts",
              "home_margin", "phase_code"]]


# %% main
def main() -> None:
    print(f"NBA context ingest -- {len(SEASONS)} seasons (regular season only)")
    all_rows = []
    for s in SEASONS:
        tg = fetch_season(s)
        g = collapse_to_games(tg, s)
        all_rows.append(g)
        # polite rate limiting on first fetch
        cache = RAW_DIR / f"leaguegamelog_{s}.parquet"
        # only sleep if the cache was freshly written during this run (rough heuristic)

    fact_game = pd.concat(all_rows, ignore_index=True)
    out = SILVER_DIR / "fact_game.parquet"
    fact_game.to_parquet(out, index=False)
    print(f"\nwrote {out} -- {len(fact_game):,} games")
    print("per-season sizes:")
    print(fact_game.groupby("season").size())
    print(f"\ntotal home_margin mean (raw HCA) = {fact_game['home_margin'].mean():+.3f} pts")
    print(f"total home_win_rate = {(fact_game['home_margin']>0).mean()*100:.2f}%")


if __name__ == "__main__":
    main()
