"""Phase 6c -- Bayesian hierarchical model for per-team HCA (OPTIONAL).

Skipped gracefully if PyMC is unavailable.
Pools per-team HCA toward the league mean using partial pooling.

D07b-1 posterior density per team (forest plot of HCA with 95% CrI)
D07b-2 shrinkage plot (raw per-team mean vs posterior mean)
D07b-3 partial pooling factor per team
"""
# %% imports
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from euroleague_hca import config
from euroleague_hca.dashboard.render import Dashboard
from euroleague_hca.warehouse import query


# %% check PyMC availability
try:
    import pymc as pm
    HAS_PYMC = True
except ImportError:
    HAS_PYMC = False


print(config.banner())

dash = Dashboard(
    title="Phase 6c -- Bayesian hierarchical (optional)",
    slug="phase-07b-hierarchical",
    subtitle="Partial pooling of per-team HCA toward the league mean",
)

if not HAS_PYMC:
    dash.add_section("skipped", "Skipped -- PyMC not installed",
                     "Install with `pip install pymc` to enable this phase. "
                     "Bayesian hierarchical partial-pooling is optional; mixedlm (Phase 6b.5) covers the same "
                     "shrinkage intuition under the classical frequentist framework.",
                     charts=[{"type": "placeholder", "id": "D07b-skip", "title": "PyMC not installed",
                              "message": "pip install pymc to enable"}])
    out = dash.write()
    print(f"dashboard: {out}")
    print("SKIPPED -- PyMC not installed (classical mixedlm covers the same use case)")
    raise SystemExit(0)


# %% data -- home games only, point_diff per (team, game)
home = query("SELECT * FROM feat_game_team WHERE is_home=1")
team_ids = sorted(home["team_id"].unique())
team_idx = {t: i for i, t in enumerate(team_ids)}
home["team_ix"] = home["team_id"].map(team_idx)
dim_team = query("SELECT team_id, name_current FROM dim_team")
team_name = dict(zip(dim_team["team_id"], dim_team["name_current"]))

N_teams = len(team_ids)
y = home["point_diff"].values
team_ix = home["team_ix"].values


# %% model
with pm.Model() as model:
    mu_league = pm.Normal("mu_league", mu=3, sigma=5)
    sigma_team = pm.HalfNormal("sigma_team", sigma=5)
    team_effect = pm.Normal("team_effect", mu=mu_league, sigma=sigma_team, shape=N_teams)
    sigma_game = pm.HalfNormal("sigma_game", sigma=15)
    pm.Normal("y", mu=team_effect[team_ix], sigma=sigma_game, observed=y)
    idata = pm.sample(1000, tune=1000, chains=2, cores=1, progressbar=False, random_seed=42)


# %% extract posteriors
post = idata.posterior
team_post = post["team_effect"].values.reshape(-1, N_teams)  # samples x teams
team_mean = team_post.mean(axis=0)
team_lo = np.percentile(team_post, 2.5, axis=0)
team_hi = np.percentile(team_post, 97.5, axis=0)

# Raw per-team mean (no pooling)
raw = home.groupby("team_id")["point_diff"].agg(["mean", "count"]).reset_index()
raw["team_ix"] = raw["team_id"].map(team_idx)
raw = raw.sort_values("team_ix")

order = np.argsort(-team_mean)

d07b_1 = {
    "type": "forest", "id": "D07b-1", "title": "Per-team HCA -- posterior mean with 95% credible interval",
    "description": "Partial pooling shrinks small-sample teams toward the league mean.",
    "teams": [
        {"label": team_name.get(team_ids[i], str(team_ids[i])),
         "mean": float(team_mean[i]), "lo": float(team_lo[i]), "hi": float(team_hi[i])}
        for i in order
    ],
    "xTitle": "HCA (pts)", "wide": True, "tall": True,
}

d07b_2 = {
    "type": "scatter", "id": "D07b-2",
    "title": "Shrinkage: raw per-team mean vs posterior mean",
    "description": "Points closer to y=x = less shrinkage; points pulled toward the dashed line = more shrinkage.",
    "xTitle": "raw mean point_diff at home", "yTitle": "posterior mean",
    "datasets": [{
        "label": "teams", "color": "#7bd8dd", "pointRadius": 6,
        "data": [{"x": float(raw.iloc[i]["mean"]), "y": float(team_mean[i]),
                  "label": team_name.get(team_ids[i], str(team_ids[i]))}
                 for i in range(N_teams)],
    }],
    "hlines": [{"y": float(team_mean.mean()), "style": "dashed", "label": "league posterior mean"}],
}

# Pooling factor: 1 - var(team_effect) / (var(team_effect) + var_residual/n)
n_games = raw["count"].values
var_team = float(post["sigma_team"].mean()) ** 2
var_game = float(post["sigma_game"].mean()) ** 2
pool_factor = 1.0 - var_team / (var_team + var_game / n_games)

d07b_3 = {
    "type": "bar", "id": "D07b-3", "title": "Partial-pooling factor per team",
    "description": "Fraction pulled toward league mean. Smaller samples => more pooling.",
    "labels": [team_name.get(team_ids[i], str(team_ids[i])) for i in order],
    "datasets": [{
        "label": "pooling factor",
        "data": [float(pool_factor[i]) for i in order],
        "color": "#4f8cff",
    }],
    "yTitle": "pool factor (0=no pooling, 1=all pooling)", "legend": False,
}


dash.kpis = [
    {"label": "League HCA (posterior mean)", "value": f"{float(post['mu_league'].mean()):+.2f}", "caption": "pts"},
    {"label": "Between-team SD", "value": f"{float(post['sigma_team'].mean()):.2f}"},
    {"label": "Within-team SD (per game)", "value": f"{float(post['sigma_game'].mean()):.2f}"},
    {"label": "Teams", "value": str(N_teams)},
]

dash.add_section("posterior", "Per-team posteriors", "Forest plot of HCA.", charts=[d07b_1])
dash.add_section("shrinkage", "Shrinkage",
                 "How much each team is pulled toward the league mean.", charts=[d07b_2, d07b_3])

out = dash.write()
print(f"dashboard: {out}")

with open(config.REPORTS_DIR / "hierarchical_output.json", "w") as f:
    json.dump({
        "mu_league": float(post["mu_league"].mean()),
        "sigma_team": float(post["sigma_team"].mean()),
        "sigma_game": float(post["sigma_game"].mean()),
    }, f, indent=2)
