"""Phase 2 -- Bronze -> Silver -> Warehouse + validation.

Builds silver tables from bronze, loads them into the SQLite warehouse, runs coverage and
referential-integrity checks, and writes the phase-02 dashboard.
"""
# %% imports
from __future__ import annotations

import logging

import pandas as pd

from euroleague_hca import config
from euroleague_hca.dashboard.render import Dashboard
from euroleague_hca.silver import build_silver
from euroleague_hca.validate import coverage_by_season, referential_integrity, sanity_checks
from euroleague_hca.warehouse import load as warehouse_load

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("02_validate")

# %% banner
print(config.banner())

# %% silver + warehouse
paths = build_silver()
log.info("silver: %s", {k: str(p) for k, p in paths.items()})
tables = warehouse_load()
log.info("warehouse: %s", tables)

# %% checks
ref = referential_integrity()
cov = coverage_by_season()
sanity = sanity_checks()
print("referential integrity:", ref)
print("overall HCA:", sanity["overall_hca"], "pts")
print("overall home win%:", sanity["overall_home_win_pct"])

# %% dashboard
dash = Dashboard(
    title="Phase 2 -- Silver build + Validation",
    slug="phase-02-coverage",
    subtitle="Schema, coverage, referential integrity, sanity checks",
)
dash.kpis = [
    {"label": "Seasons", "value": str(len(cov)), "caption": f"{cov['season'].min()}-{cov['season'].max()}" if len(cov) else ""},
    {"label": "Games", "value": str(sanity["n_games"])},
    {"label": "League HCA", "value": f"{sanity['overall_hca']:+.2f} pts", "caption": "home margin, all games"},
    {"label": "Home win %", "value": f"{sanity['overall_home_win_pct']*100:.1f}%"},
]

dash.add_section("coverage", "Per-season coverage", "Games per season, home-win rate, league HCA.", charts=[
    {
        "type": "bar", "id": "P02-1", "title": "Games per season",
        "labels": cov["season"].astype(str).tolist(),
        "datasets": [{"label": "games", "data": cov["n_games"].tolist()}],
    },
    {
        "type": "line", "id": "P02-2", "title": "League HCA per season",
        "labels": cov["season"].astype(str).tolist(),
        "datasets": [{"label": "HCA (pts)", "data": cov["league_hca_pts"].tolist()}],
        "yTitle": "HCA (points)",
    },
    {
        "type": "line", "id": "P02-3", "title": "Home win % per season",
        "labels": cov["season"].astype(str).tolist(),
        "datasets": [{"label": "home win %", "data": cov["home_win_pct"].tolist()}],
        "yTitle": "win %",
    },
    {
        "type": "table", "id": "P02-4", "title": "Referential integrity", "wide": True,
        "columns": ["Check", "Violations"],
        "rows": [[k, v] for k, v in ref.items()],
        "footnote": "All counts should be zero.",
    },
])

out = dash.write()
print(f"dashboard: {out}")
