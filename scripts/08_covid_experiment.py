"""Phase 7 -- COVID natural experiment.

Approximates a Difference-in-Differences comparison of HCA across three regimes:
  * pre-COVID (2015-16..2018-19)
  * COVID restricted / empty arenas (2019-20..2020-21)
  * post-COVID (2021-22..2024-25)

D08-1 HCA over time with regime shading
D08-2 HCA distribution per regime (box/violin)
D08-3 regime means with 95% CI
D08-4 per-team HCA change pre -> during -> post
D08-5 DiD estimates with 95% CI
"""
# %% imports
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from euroleague_hca import config
from euroleague_hca.dashboard.render import Dashboard
from euroleague_hca.warehouse import query


# %% data
print(config.banner())
games = query("SELECT * FROM fact_game")
dim_team = query("SELECT team_id, name_current FROM dim_team")
team_name = dict(zip(dim_team["team_id"], dim_team["name_current"]))


# %% regime labels
def regime(season: int) -> str:
    if season <= 2018:
        return "pre"
    if season <= 2020:
        return "covid"
    return "post"


games["regime"] = games["season"].apply(regime)


# %% bootstrap CI helper
def boot_ci(x: np.ndarray, n: int = 1000, seed: int = 42):
    if len(x) == 0:
        return (np.nan, np.nan, np.nan)
    rng = np.random.default_rng(seed)
    samples = rng.choice(x, size=(n, len(x)), replace=True).mean(axis=1)
    return float(np.mean(x)), float(np.percentile(samples, 2.5)), float(np.percentile(samples, 97.5))


# %% HCA over time (by season)
season_hca = games.groupby("season").agg(
    mean=("home_margin", "mean"),
    n=("home_margin", "count"),
).reset_index()
season_hca["regime"] = season_hca["season"].apply(regime)


# %% per-regime summary
regime_order = ["pre", "covid", "post"]
regime_stats = {}
for r in regime_order:
    vals = games.loc[games["regime"] == r, "home_margin"].values
    m, lo, hi = boot_ci(vals)
    regime_stats[r] = {"mean": m, "lo": lo, "hi": hi, "n": int(len(vals))}


# %% per-team HCA by regime
team_regime = games.groupby(["home_team_id", "regime"])["home_margin"].mean().unstack(fill_value=np.nan).reset_index()
team_regime["name"] = team_regime["home_team_id"].map(team_name)
# keep teams with data in all three regimes
team_regime = team_regime.dropna(subset=regime_order, how="any")


# %% DiD: pre->covid, pre->post, covid->post
def diff_in_diff(regime_a, regime_b):
    a = games.loc[games["regime"] == regime_a, "home_margin"].values
    b = games.loc[games["regime"] == regime_b, "home_margin"].values
    diff = b.mean() - a.mean()
    rng = np.random.default_rng(42)
    samples = []
    for _ in range(1000):
        sa = rng.choice(a, size=len(a), replace=True).mean()
        sb = rng.choice(b, size=len(b), replace=True).mean()
        samples.append(sb - sa)
    return float(diff), float(np.percentile(samples, 2.5)), float(np.percentile(samples, 97.5))


did = {
    "covid - pre":   diff_in_diff("pre", "covid"),
    "post - covid":  diff_in_diff("covid", "post"),
    "post - pre":    diff_in_diff("pre", "post"),
}


# %% dashboard
dash = Dashboard(
    title="Phase 7 -- COVID natural experiment",
    slug="phase-08-covid",
    subtitle="How did HCA change when arenas emptied?",
)

regime_color = {"pre": "#4f8cff", "covid": "#f06470", "post": "#6fcf97"}

d08_1 = {
    "type": "line", "id": "D08-1",
    "title": "HCA over time with COVID regime shading",
    "description": "pre (2015--18) / covid (2019--20) / post (2021--).",
    "xTitle": "season start year", "yTitle": "HCA (pts)",
    "datasets": [{
        "label": "league HCA",
        "data": [{"x": int(s), "y": float(m)} for s, m in zip(season_hca["season"], season_hca["mean"])],
        "color": "#4f8cff", "tension": 0.3,
    }],
    "hlines": [{"y": 0, "style": "dashed"}],
    "vbands": [
        {"x0": 2019, "x1": 2020, "color": "rgba(240, 100, 112, 0.15)", "label": "covid"},
    ],
}

d08_2 = {
    "type": "boxplot_points", "id": "D08-2",
    "title": "HCA distribution per regime",
    "description": "Each point is a (team, season) mean. Shows spread inside each regime.",
    "xTitle": "regime", "yTitle": "team-season HCA (pts)",
    "datasets": [{
        "label": r,
        "color": regime_color[r],
        "data": [{"x": r, "y": float(v)}
                 for v in games[games["regime"] == r].groupby(["home_team_id", "season"])["home_margin"].mean().values],
    } for r in regime_order],
}

d08_3 = {
    "type": "forest", "id": "D08-3", "title": "Regime mean HCA with 95% CI",
    "teams": [
        {"label": r, "mean": regime_stats[r]["mean"],
         "lo": regime_stats[r]["lo"], "hi": regime_stats[r]["hi"]}
        for r in regime_order
    ],
    "xTitle": "HCA (pts)",
}

d08_4 = {
    "type": "parallel", "id": "D08-4",
    "title": "Per-team HCA: pre -> covid -> post",
    "description": "Each line is one team across the three regimes.",
    "xTitle": "regime", "yTitle": "HCA (pts)",
    "series": [
        {"label": r["name"],
         "data": [{"x": reg, "y": float(r[reg])} for reg in regime_order]}
        for _, r in team_regime.iterrows()
    ],
}

d08_5 = {
    "type": "forest", "id": "D08-5", "title": "Difference-in-differences estimates",
    "description": "95% CI bootstrap on the mean change.",
    "teams": [
        {"label": k, "mean": v[0], "lo": v[1], "hi": v[2]}
        for k, v in did.items()
    ],
    "xTitle": "delta HCA (pts)",
}


dash.kpis = [
    {"label": "Pre-COVID HCA", "value": f"{regime_stats['pre']['mean']:+.2f}",
     "caption": f"n={regime_stats['pre']['n']}"},
    {"label": "COVID HCA", "value": f"{regime_stats['covid']['mean']:+.2f}",
     "caption": f"n={regime_stats['covid']['n']}"},
    {"label": "Post-COVID HCA", "value": f"{regime_stats['post']['mean']:+.2f}",
     "caption": f"n={regime_stats['post']['n']}"},
    {"label": "DiD covid -- pre", "value": f"{did['covid - pre'][0]:+.2f}",
     "caption": f"[{did['covid - pre'][1]:+.2f}, {did['covid - pre'][2]:+.2f}]"},
]

dash.add_section("timeline", "HCA timeline",
                 "Season-by-season with regime shading.", charts=[d08_1])
dash.add_section("regime_compare", "Regime comparison",
                 "Distribution and means per regime.", charts=[d08_2, d08_3])
dash.add_section("teams", "Per-team regime change", "", charts=[d08_4])
dash.add_section("did", "Difference-in-differences",
                 "Direct estimates of how HCA shifted between regimes.", charts=[d08_5])

out = dash.write()
print(f"dashboard: {out}")
print("DiD:")
for k, v in did.items():
    print(f"  {k:15s}: {v[0]:+.2f} pts [{v[1]:+.2f}, {v[2]:+.2f}]")

with open(config.REPORTS_DIR / "covid_output.json", "w") as f:
    json.dump({
        "regime_stats": regime_stats,
        "did": {k: {"mean": v[0], "lo": v[1], "hi": v[2]} for k, v in did.items()},
    }, f, indent=2)
