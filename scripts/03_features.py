"""Phase 3 -- Feature engineering (gold layer + Elo walk-forward).

Produces:
- feat_game_team
- feat_team_season_hca
- feat_pairwise_same_opponent
- feat_team_attendance_slope
"""
# %% imports
from __future__ import annotations

import logging

from euroleague_hca import config
from euroleague_hca.gold import build_gold
from euroleague_hca.warehouse import load as warehouse_load

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

# %% banner
print(config.banner())

# %% build
counts = build_gold()
print("gold counts:", counts)

# %% reload warehouse so gold tables are queryable
tables = warehouse_load()
print("warehouse tables:", tables)
