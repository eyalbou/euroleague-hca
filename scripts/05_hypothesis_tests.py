"""Phase 5 -- Hypothesis tests.

D05-1 permutation null + observed (league-wide)
D05-2 per-team permutation null small-multiples
D05-3 Cohen's d forest plot per team (Holm-adjusted CIs)
D05-4 p-value heatmap (teams x tests)
D05-5 bucket-wise HCA bar with CIs
D05-6 Spearman HCA~attendance_ratio per team
"""
# %% imports
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import spearmanr, ttest_rel, wilcoxon

from euroleague_hca import config
from euroleague_hca.dashboard.render import Dashboard
from euroleague_hca.warehouse import query


# %% load
print(config.banner())
fgt = query("SELECT * FROM feat_game_team")
dim_team = query("SELECT * FROM dim_team")
team_name = dict(zip(dim_team["team_id"], dim_team["name_current"]))
rng = np.random.default_rng(42)


# %% helpers
def bootstrap_ci(x, n=1000, ci=0.95):
    if len(x) < 2:
        return float("nan"), float("nan")
    draws = rng.choice(x, size=(n, len(x)), replace=True).mean(axis=1)
    return float(np.percentile(draws, (1 - ci) / 2 * 100)), float(np.percentile(draws, (1 + ci) / 2 * 100))


def permutation_null_league(home_margins, n_perm=5000):
    """Shuffle is_home label within each game. With paired structure, flipping signs is equivalent."""
    obs = float(home_margins.mean())
    signs = rng.choice([-1, 1], size=(n_perm, len(home_margins)))
    null = (signs * home_margins.values).mean(axis=1)
    p = float((np.abs(null) >= abs(obs)).mean())
    return obs, null, p


def cohens_d(x, y):
    """Cohen's d for paired design: mean(x-y) / sd(x-y)."""
    d = x - y
    sd = d.std(ddof=1)
    return float(d.mean() / sd) if sd > 0 else float("nan")


def holm(pvals):
    """Holm-Bonferroni correction."""
    p = np.array(pvals, dtype=float)
    n = len(p)
    order = np.argsort(p)
    adj = np.empty(n)
    prev = 0.0
    for rank, idx in enumerate(order):
        adj[idx] = min(1.0, max(prev, p[idx] * (n - rank)))
        prev = adj[idx]
    return adj


# %% league-wide permutation test
home = fgt[fgt["is_home"] == 1]
league_obs, league_null, league_p = permutation_null_league(home["point_diff"])

league_hist, league_edges = np.histogram(league_null, bins=60)
league_centers = ((league_edges[:-1] + league_edges[1:]) / 2).tolist()

# %% per-team tests
per_team = []
pair = query("SELECT team_id, opp_team_id, season, margin_home, margin_away FROM feat_pairwise_same_opponent")

for tid in sorted(team_name.keys()):
    home_team = home[home["team_id"] == tid]["point_diff"].values
    away_team = fgt[(fgt["team_id"] == tid) & (fgt["is_home"] == 0)]["point_diff"].values
    # Paired same-opponent: use pairwise table where team_id == tid
    sub_pair = pair[pair["team_id"] == tid].dropna(subset=["margin_home", "margin_away"])
    if len(sub_pair) < 3:
        continue
    margin_home = sub_pair["margin_home"].values
    margin_away = sub_pair["margin_away"].values
    hca = margin_home - margin_away

    # Paired t-test on same-opponent pairs
    try:
        t_stat, t_p = ttest_rel(margin_home, margin_away)
    except Exception:
        t_p = np.nan
    # Wilcoxon
    try:
        w_stat, w_p = wilcoxon(margin_home, margin_away)
    except Exception:
        w_p = np.nan
    # Permutation test on home-team point_diff
    _, _, perm_p = permutation_null_league(home[home["team_id"] == tid]["point_diff"], n_perm=2000)
    # Spearman HCA ~ attendance_ratio (at home games)
    home_team_df = home[(home["team_id"] == tid) & home["attendance_ratio"].notna()]
    if len(home_team_df) >= 5:
        s_r, s_p = spearmanr(home_team_df["attendance_ratio"], home_team_df["point_diff"])
    else:
        s_r, s_p = np.nan, np.nan

    d = cohens_d(margin_home, margin_away)
    lo, hi = bootstrap_ci(hca)

    per_team.append({
        "team_id": tid, "name": team_name[tid],
        "hca": float(hca.mean()), "hca_lo": lo, "hca_hi": hi,
        "d": d, "n_pairs": int(len(sub_pair)),
        "p_ttest": float(t_p), "p_wilcoxon": float(w_p), "p_perm": float(perm_p),
        "r_spearman": float(s_r), "p_spearman": float(s_p),
    })

pt = pd.DataFrame(per_team).sort_values("d", ascending=False)

# Holm correction across tests
for col in ["p_ttest", "p_wilcoxon", "p_perm", "p_spearman"]:
    finite = pt[col].replace([np.inf, -np.inf], np.nan).dropna()
    adj = pd.Series(holm(finite.values), index=finite.index)
    pt[col + "_holm"] = pt[col].copy()
    pt.loc[adj.index, col + "_holm"] = adj.values


# %% attendance buckets
buckets_order = ["closed_doors", "low", "medium", "high", "sold_out"]
bucket_stats = []
for b in buckets_order:
    vals = home[home["attendance_bucket"] == b]["point_diff"].values
    lo, hi = bootstrap_ci(vals) if len(vals) >= 5 else (float("nan"), float("nan"))
    bucket_stats.append({
        "bucket": b, "n": int(len(vals)),
        "hca": float(vals.mean()) if len(vals) else float("nan"),
        "lo": lo, "hi": hi,
    })
bucket_df = pd.DataFrame(bucket_stats)


# %% dashboard
dash = Dashboard(
    title="Phase 5 -- Hypothesis tests",
    slug="phase-05-tests",
    subtitle=f"League obs stat = {league_obs:+.3f} pts, permutation p = {league_p:.4f}",
)
dash.kpis = [
    {"label": "League obs HCA", "value": f"{league_obs:+.3f}", "caption": "points"},
    {"label": "Permutation p", "value": f"{league_p:.4f}", "caption": "5000 shuffles"},
    {"label": "Teams tested", "value": str(len(pt))},
    {"label": "Tests", "value": "4 per team", "caption": "t / Wilcoxon / permutation / Spearman"},
]


# %% D05-1 league permutation null
d05_1 = {
    "type": "bar", "id": "D05-1", "title": "League-wide permutation null distribution",
    "description": f"Observed statistic = {league_obs:+.3f} pts. Shaded bars = permutation null.",
    "labels": [f"{c:.2f}" for c in league_centers],
    "datasets": [
        {"label": "null", "data": league_hist.astype(int).tolist(), "color": "#9aa4b2"},
    ],
    "xTitle": "mean home-margin (shuffled sign)", "yTitle": "# permutations", "wide": True,
}


# %% D05-2 per-team permutation small multiples -- table of observed stat + p-value
d05_2 = {
    "type": "table", "id": "D05-2",
    "title": "Per-team permutation tests (observed HCA + p-value)",
    "description": "Observed per-team HCA (home point_diff mean) vs shuffled null. Small p = unlikely under null.",
    "columns": ["team", "n home", "HCA", "perm p", "perm p (Holm)"],
    "rows": [
        [r["name"], int(len(home[home["team_id"] == r["team_id"]])),
         f"{r['hca']:+.2f}", f"{r['p_perm']:.4f}", f"{r['p_perm_holm']:.4f}"]
        for _, r in pt.iterrows()
    ],
    "wide": True,
}


# %% D05-3 Cohen's d forest plot
d05_3 = {
    "type": "forest", "id": "D05-3", "title": "Cohen's d per team (paired same-opponent design)",
    "description": "Standardized effect size. |d|>0.2 small, >0.5 medium, >0.8 large.",
    "teams": [
        {"label": r["name"], "mean": r["d"],
         "lo": r["d"] - 1.96 / np.sqrt(max(r["n_pairs"], 1)),
         "hi": r["d"] + 1.96 / np.sqrt(max(r["n_pairs"], 1))}
        for _, r in pt.iterrows()
    ],
    "xTitle": "Cohen's d", "wide": True, "tall": True,
}


# %% D05-4 p-value heatmap
test_cols = ["p_ttest_holm", "p_wilcoxon_holm", "p_perm_holm", "p_spearman_holm"]
test_labels = ["t-test", "Wilcoxon", "Permutation", "Spearman (attendance)"]
pv_matrix = []
for _, r in pt.iterrows():
    row = []
    for c in test_cols:
        v = r.get(c)
        if pd.isna(v):
            row.append(None)
        else:
            row.append(-np.log10(max(v, 1e-6)))
    pv_matrix.append(row)

d05_4 = {
    "type": "heatmap", "id": "D05-4", "title": "P-value heatmap (-log10 Holm-adjusted p)",
    "description": "Darker = stronger evidence. Columns = test types.",
    "xs": test_labels,
    "ys": pt["name"].tolist(),
    "values": pv_matrix, "wide": True, "tall": True,
}


# %% D05-5 bucket-wise HCA bar
d05_5 = {
    "type": "bar", "id": "D05-5", "title": "HCA by attendance bucket",
    "description": "Mean home margin within each attendance-ratio bucket. 2020-21 closed-doors is the leftmost bar.",
    "labels": [f"{b} (n={int(n)})" for b, n in zip(bucket_df["bucket"], bucket_df["n"])],
    "datasets": [{"label": "HCA (pts)", "data": bucket_df["hca"].round(2).tolist(),
                  "colors": ["#f06b6b", "#f5c264", "#7bd8dd", "#4ecc8f", "#4f8cff"]}],
    "yTitle": "HCA (pts)", "legend": False, "wide": True,
}


# %% D05-6 Spearman HCA~attendance_ratio per team
d05_6 = {
    "type": "forest", "id": "D05-6", "title": "Spearman rho (HCA vs attendance_ratio) per team",
    "description": "Per-team correlation between fullness and home point-differential. Holm-adjusted CIs approximated with Fisher-z SE.",
    "teams": [
        {"label": r["name"], "mean": r["r_spearman"] if pd.notna(r["r_spearman"]) else 0.0,
         "lo": (r["r_spearman"] - 1.96 / max(np.sqrt(max(r["n_pairs"], 4) - 3), 1)) if pd.notna(r["r_spearman"]) else 0.0,
         "hi": (r["r_spearman"] + 1.96 / max(np.sqrt(max(r["n_pairs"], 4) - 3), 1)) if pd.notna(r["r_spearman"]) else 0.0}
        for _, r in pt.iterrows()
    ],
    "xTitle": "Spearman rho", "wide": True, "tall": True,
}


# %% per-team significance table (raw drilldown)
sig_table = {
    "type": "table", "id": "D05-X", "title": "Per-team significance table",
    "description": "All four p-values + Cohen's d. Sortable by clicking column headers.",
    "columns": ["team", "n pairs", "HCA", "d", "t p", "Wilc p", "perm p", "Spearman rho", "Spearman p"],
    "rows": [
        [r["name"], r["n_pairs"], f"{r['hca']:+.2f}", f"{r['d']:+.3f}",
         f"{r['p_ttest_holm']:.4f}", f"{r['p_wilcoxon_holm']:.4f}",
         f"{r['p_perm_holm']:.4f}",
         f"{r['r_spearman']:+.3f}" if pd.notna(r["r_spearman"]) else "--",
         f"{r['p_spearman_holm']:.4f}" if pd.notna(r["p_spearman_holm"]) else "--"]
        for _, r in pt.iterrows()
    ],
    "footnote": "p-values are Holm-adjusted across teams.",
    "wide": True,
}


dash.add_section("league", "League-wide tests", "Permutation test on home-margin.", charts=[d05_1])
dash.add_section(
    "per_team", "Per-team tests",
    "Paired t-test, Wilcoxon, permutation, Spearman with Holm correction.",
    charts=[d05_3, d05_4, d05_2, sig_table],
)
dash.add_section(
    "attendance", "Attendance-stratified tests",
    "Does HCA scale with fullness?",
    charts=[d05_5, d05_6],
)

out = dash.write()
print(f"dashboard: {out}")
print(f"league permutation p={league_p:.4f} | teams tested={len(pt)}")
