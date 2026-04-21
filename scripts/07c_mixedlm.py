"""Phase 6b.5 -- Classical hierarchical model (statsmodels mixedlm).

Per-team random intercept + random slope on attendance_ratio.
Target: point_diff (home games only).

D07c-1 per-team attendance-sensitivity forest plot
D07c-2 per-team random intercept vs random slope scatter
D07c-3 variance-components breakdown
"""
# %% imports
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

from euroleague_hca import config
from euroleague_hca.dashboard.render import Dashboard
from euroleague_hca.warehouse import query


# %% data -- one row per HOME game, per team
print(config.banner())
home = query("SELECT * FROM feat_game_team WHERE is_home=1")
home["attendance_ratio"] = home["attendance_ratio"].fillna(home["attendance_ratio"].mean())

dim_team = query("SELECT team_id, name_current FROM dim_team")
team_name = dict(zip(dim_team["team_id"], dim_team["name_current"]))

# Filter out teams with too few home games -- random slopes are unidentifiable
# when within-team variance in attendance_ratio is near zero.
team_n = home.groupby("team_id").size()
keep_teams = team_n[team_n >= 20].index.tolist()
print(f"  filtered: keeping {len(keep_teams)}/{len(team_n)} teams with >=20 home games")
home = home[home["team_id"].isin(keep_teams)].copy()


# %% model: try random intercept + slope first, fall back to intercept-only on singular
def fit_mixedlm(re_formula: str | None):
    return smf.mixedlm(
        "point_diff ~ 1 + attendance_ratio + is_playoff",
        data=home,
        groups=home["team_id"],
        re_formula=re_formula,
    ).fit(method="lbfgs", maxiter=300)

ok = False
re_used = None
result = None
for attempt in ["~1 + attendance_ratio", "~1"]:
    try:
        result = fit_mixedlm(attempt)
        ok = True
        re_used = attempt
        print(f"  mixedlm converged with re_formula='{attempt}'")
        break
    except Exception as e:  # noqa: BLE001
        print(f"  mixedlm failed with re_formula='{attempt}': {e}")

if not ok:
    print("mixedlm failed entirely")


# %% extract per-team random effects
if ok:
    fe = result.fe_params.to_dict()
    re = result.random_effects
    has_random_slope = re_used and "attendance_ratio" in re_used
    re_df = pd.DataFrame([
        {"team_id": k, "r_intercept": float(v["Group"]),
         "r_slope": float(v.get("attendance_ratio", 0.0)) if has_random_slope else 0.0}
        for k, v in re.items()
    ])
    re_df["total_hca_intercept"] = fe.get("Intercept", 0.0) + re_df["r_intercept"]
    re_df["total_slope"] = fe.get("attendance_ratio", 0.0) + re_df["r_slope"]
    re_df["name"] = re_df["team_id"].map(team_name)
    re_df = re_df.sort_values("total_slope", ascending=False)

    # Variance components
    cov_re = result.cov_re
    var_intercept = float(cov_re.iloc[0, 0]) if hasattr(cov_re, 'iloc') else float(cov_re[0][0])
    var_slope = float(cov_re.iloc[1, 1]) if cov_re.shape[0] > 1 else 0.0
    var_residual = float(result.scale)


# %% dashboard
dash = Dashboard(
    title="Phase 6b.5 -- Classical hierarchical (mixedlm)",
    slug="phase-07c-mixedlm",
    subtitle="Per-team random intercept + random slope on attendance_ratio",
)

if not ok:
    dash.add_section("failed", "Model did not converge",
                     "statsmodels mixedlm failed. See logs.",
                     charts=[{"type": "placeholder", "id": "D07c-fail", "title": "mixedlm failed", "message": "model did not fit"}])
    dash.write()
    print("FAILED -- see logs")
    raise SystemExit(0)

# SE approximation for random slopes
slope_se = np.sqrt(var_slope) if var_slope > 0 else 0.5

d07c_1 = {
    "type": "forest", "id": "D07c-1",
    "title": "Per-team attendance-sensitivity slope (random slope on attendance_ratio)",
    "description": f"Fixed effect slope = {fe.get('attendance_ratio', 0.0):+.2f}. Total = fixed + random.",
    "teams": [
        {"label": r["name"], "mean": r["total_slope"],
         "lo": r["total_slope"] - 1.96 * slope_se,
         "hi": r["total_slope"] + 1.96 * slope_se}
        for _, r in re_df.iterrows()
    ],
    "xTitle": "slope (pts per unit attendance_ratio)", "wide": True, "tall": True,
}

d07c_2 = {
    "type": "scatter", "id": "D07c-2",
    "title": "Random intercept vs random slope per team",
    "description": "X = baseline HCA (intercept), Y = crowd sensitivity (slope).",
    "xTitle": "total HCA intercept (pts)", "yTitle": "total slope",
    "datasets": [{
        "label": "teams",
        "data": [{"x": r["total_hca_intercept"], "y": r["total_slope"], "label": r["name"]}
                 for _, r in re_df.iterrows()],
        "color": "#7bd8dd", "pointRadius": 7,
    }],
}

total_var = var_intercept + var_slope + var_residual
d07c_3 = {
    "type": "bar", "id": "D07c-3", "title": "Variance components",
    "description": "How much point_diff variance is attributable to each source?",
    "labels": ["between-team intercept", "between-team slope", "within-team residual"],
    "datasets": [{
        "label": "variance share",
        "data": [var_intercept / total_var, var_slope / total_var, var_residual / total_var],
        "colors": ["#4f8cff", "#f5c264", "#9aa4b2"],
    }],
    "yTitle": "share of variance", "legend": False,
}


dash.kpis = [
    {"label": "Fixed intercept", "value": f"{fe.get('Intercept', 0.0):+.2f}", "caption": "league baseline HCA"},
    {"label": "Fixed slope", "value": f"{fe.get('attendance_ratio', 0.0):+.2f}",
     "caption": "avg effect of attendance_ratio"},
    {"label": "Teams", "value": str(len(re_df))},
    {"label": "Residual SD", "value": f"{np.sqrt(var_residual):.2f}",
     "caption": "pts within-team noise"},
]

dash.add_section("team_effects", "Per-team effects",
                 "Random intercepts and slopes.", charts=[d07c_1, d07c_2])
dash.add_section("variance", "Variance components",
                 "Between-team vs within-team.", charts=[d07c_3])

out = dash.write()
print(f"dashboard: {out}")

with open(config.REPORTS_DIR / "mixedlm_output.json", "w") as f:
    json.dump({
        "fixed_effects": fe,
        "team_slopes": [
            {"team_id": r["team_id"], "name": r["name"],
             "total_slope": r["total_slope"], "total_intercept": r["total_hca_intercept"]}
            for _, r in re_df.iterrows()
        ],
        "variance_components": {
            "intercept": var_intercept, "slope": var_slope, "residual": var_residual,
        },
    }, f, indent=2)
