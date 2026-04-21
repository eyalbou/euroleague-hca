"""Phase 4 extension -- advanced descriptive (D04-17..D04-21).

Requires PBP / shot / referee / arena geo data. In the mock pipeline we don't ingest those,
so these charts render as graceful placeholders with a "requires X data" message. The only
graph we can render from existing data is the head-to-head HCA matrix (D04-21).
"""
# %% imports
from __future__ import annotations

import numpy as np
import pandas as pd

from euroleague_hca import config
from euroleague_hca.dashboard.render import Dashboard
from euroleague_hca.warehouse import query


# %% load
print(config.banner())
fgt = query("SELECT * FROM feat_game_team")
dim_team = query("SELECT * FROM dim_team")
team_name = dict(zip(dim_team["team_id"], dim_team["name_current"]))


# %% head-to-head HCA matrix (D04-21) -- only graph computable without PBP/shot/geo
pairs = query(
    "SELECT team_id, opp_team_id, margin_home, margin_away, hca_pair_adj "
    "FROM feat_pairwise_same_opponent"
)
teams_sorted = sorted(team_name.keys(), key=lambda t: team_name[t])
h2h = np.full((len(teams_sorted), len(teams_sorted)), np.nan)
tidx = {t: i for i, t in enumerate(teams_sorted)}
# Aggregate across seasons: mean hca_pair_adj when A hosts B
agg = pairs.groupby(["team_id", "opp_team_id"])["hca_pair_adj"].mean().reset_index()
for _, r in agg.iterrows():
    ai = tidx.get(r["team_id"])
    bi = tidx.get(r["opp_team_id"])
    if ai is not None and bi is not None:
        h2h[ai, bi] = r["hca_pair_adj"]

d04_21 = {
    "type": "heatmap", "id": "D04-21", "title": "Head-to-head HCA matrix (paired)",
    "description": "Cell [row, col] = mean home-minus-away margin when row hosts col.",
    "xs": [team_name[t] for t in teams_sorted],
    "ys": [team_name[t] for t in teams_sorted],
    "values": h2h.tolist(),
    "wide": True, "tall": True,
}


# %% placeholders for data-dependent graphs
def placeholder(id_: str, title: str, need: str) -> dict:
    return {
        "type": "placeholder", "id": id_, "title": title,
        "description": f"Requires {need} (not ingested in this mock run). Flip ELH_MOCK=0 with full live ingest to populate.",
        "message": f"{title}: requires {need}",
    }


d04_17 = placeholder("D04-17", "Quarter-by-quarter HCA", "play-by-play (fact_play_by_play)")
d04_18 = placeholder("D04-18", "Shot-zone eFG% home minus away", "shot data (fact_shot)")
d04_19 = placeholder("D04-19", "Travel-distance effect", "arena lat/lon (data/reference/arena_geo.csv)")
d04_20 = placeholder("D04-20", "Referee HCA", "play-by-play + dim_referee")


# %% dashboard
dash = Dashboard(
    title="Phase 4b -- Descriptive extension",
    slug="phase-04b-descriptive-ext",
    subtitle="Advanced descriptive analyses (PBP / shot / geo / referee / head-to-head)",
)
dash.add_section(
    "advanced", "Advanced descriptive",
    "D04-17..D04-21. Gated on ingest; placeholders until PBP / shot / geo / referee data is pulled.",
    charts=[d04_17, d04_18, d04_19, d04_20, d04_21],
)

out = dash.write()
print(f"dashboard: {out}")
