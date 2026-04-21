"""Phase 1 -- Ingestion.

Pulls the schedule/game metadata/boxscore triple for each season into data/raw/ and writes the
bronze parquet. Honors SAMPLE_MODE. If the live API is unreachable, falls back to the mock
generator (tagged data_source='mock') so downstream phases can still run end-to-end.

Run:
    python scripts/01_ingest.py

Environment:
    ELH_SAMPLE=1|0   sample (default) vs full
    ELH_MOCK=1       force mock (skip network)
    ELH_MOCK=0       force live (fail if unreachable)
"""
# %% imports
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from euroleague_hca import config
from euroleague_hca.bronze import mock_to_bronze, live_to_bronze
from euroleague_hca.dashboard.render import Dashboard
from euroleague_hca.ingest import mock, swagger_direct

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("01_ingest")


# %% banner
print(config.banner())

# %% decide source
seasons = config.seasons_active()
mock_flag = os.environ.get("ELH_MOCK", "auto")

if mock_flag == "1":
    source = "mock"
    log.info("ELH_MOCK=1 -- forcing mock")
elif mock_flag == "0":
    if not swagger_direct.is_reachable():
        raise RuntimeError("ELH_MOCK=0 but live EuroLeague API is unreachable")
    source = "live"
else:
    source = "live" if swagger_direct.is_reachable() else "mock"

log.info("data source: %s", source)

# %% run
run_start = time.time()
manifest_rows: list[dict] = []

if source == "mock":
    mock.write_raw(seasons)
    for s in seasons:
        manifest_rows.append({
            "run_id": "mock-run", "source": "mock", "endpoint": "fact_game",
            "url": "n/a", "params": json.dumps({"season": s}),
            "timestamp": datetime.now(timezone.utc).isoformat(), "http_status": 200,
            "rows_returned": len([g for g in mock.generate([s])["fact_game"]]),
            "file_path": str(config.RAW_DIR / "mock" / str(s) / "fact_game.json.gz"),
            "content_hash": "deterministic",
        })
    counts = mock_to_bronze()
else:
    # Live pull
    swagger_direct.clubs()
    swagger_direct.venues()
    
    for s in seasons:
        games = swagger_direct.list_games(s)
        log.info("season %d: %d games listed", s, len(games))
        manifest_rows.append({
            "run_id": datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S"),
            "source": "live", "endpoint": "games_list", "url": "v2/games",
            "params": json.dumps({"season": s}), "timestamp": datetime.now(timezone.utc).isoformat(),
            "http_status": 200, "rows_returned": len(games),
            "file_path": "data/raw/live/...", "content_hash": "",
        })
        max_games = config.SAMPLE_GAMES_PER_SEASON if config.SAMPLE_MODE else None
        
        # Only process played games
        played_games = [g for g in games if g.get("played", False)]
        
        for i, g in enumerate(played_games[:max_games]):
            gc = g.get("gameCode") or g.get("game_code") or g.get("id")
            if gc:
                swagger_direct.game_metadata(s, int(gc))
                swagger_direct.boxscore(s, int(gc))
            if i % 50 == 0:
                log.info(f"Processed {i}/{len(played_games[:max_games])} games for season {s}")
                
    counts = live_to_bronze()

log.info("bronze: %s", counts)

# %% write manifest
if manifest_rows:
    import pyarrow as pa
    import pyarrow.parquet as pq

    man_df = pd.DataFrame(manifest_rows)
    pq.write_table(pa.Table.from_pandas(man_df, preserve_index=False), config.INGEST_MANIFEST)

# %% dashboard
runtime = time.time() - run_start
dash = Dashboard(
    title="Phase 1 -- Ingestion",
    slug="phase-01-ingest",
    subtitle=f"Pulled {len(seasons)} season(s) from source={source} in {runtime:.1f}s",
)
dash.kpis = [
    {"label": "Seasons", "value": str(len(seasons)), "caption": ", ".join(str(s) for s in seasons)},
    {"label": "Games", "value": str(counts.get("fact_game", 0)), "caption": f"source={source}"},
    {"label": "Teams", "value": str(counts.get("dim_team", 0)), "caption": ""},
    {"label": "Runtime", "value": f"{runtime:.1f}s", "caption": "wall clock"},
]

# coverage heatmap per season
if counts.get("fact_game"):
    games_df = pd.read_parquet(config.BRONZE_DIR / "fact_game")
    cov = games_df.groupby("season").size().reset_index(name="n_games")
    dash.add_section("coverage", "Per-season coverage", "Games ingested per season.", charts=[
        {
            "type": "bar", "id": "P01-1", "title": "Games per season",
            "labels": cov["season"].astype(str).tolist(),
            "datasets": [{"label": "games", "data": cov["n_games"].tolist()}],
            "yTitle": "games", "xTitle": "season",
        }
    ])

out = dash.write()
print(f"dashboard: {out}")
