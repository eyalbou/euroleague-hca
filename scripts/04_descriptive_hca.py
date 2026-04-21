"""Phase 4 -- Descriptive HCA.

Produces dashboards/phase-04-descriptive.html with ALL D04 graphs D04-1..D04-16.
"""
# %% imports
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from euroleague_hca import config
from euroleague_hca.dashboard.render import Dashboard
from euroleague_hca.warehouse import query

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("04_descriptive")


# %% load
print(config.banner())
fgt = query("SELECT * FROM feat_game_team")
fgt["date"] = pd.to_datetime(fgt["date"])
ts_hca = query("SELECT * FROM feat_team_season_hca")
fg = query("SELECT * FROM fact_game")
fg["date"] = pd.to_datetime(fg["date"])
dim_team = query("SELECT * FROM dim_team")
team_name = dict(zip(dim_team["team_id"], dim_team["name_current"]))


# %% helpers
def bootstrap_ci(x: np.ndarray, n: int = 1000, ci: float = 0.95) -> tuple[float, float]:
    if len(x) < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(42)
    draws = rng.choice(x, size=(n, len(x)), replace=True).mean(axis=1)
    return float(np.percentile(draws, (1 - ci) / 2 * 100)), float(np.percentile(draws, (1 + ci) / 2 * 100))


def spearman(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Spearman rho + two-sided p-value via scipy."""
    from scipy.stats import spearmanr
    r, p = spearmanr(x, y)
    return float(r), float(p)


def pearson(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    from scipy.stats import pearsonr
    r, p = pearsonr(x, y)
    return float(r), float(p)


# %% headline numbers
league_hca = float(fgt.loc[fgt["is_home"] == 1, "point_diff"].mean())
league_home_win = float(fgt.loc[fgt["is_home"] == 1, "point_diff"].gt(0).mean())
n_games = int(len(fg))


# %% per-team HCA table (home perspective)
home = fgt[fgt["is_home"] == 1]
per_team = []
for tid, sub in home.groupby("team_id"):
    lo, hi = bootstrap_ci(sub["point_diff"].values)
    per_team.append({
        "team_id": tid, "name": team_name.get(tid, tid),
        "hca": float(sub["point_diff"].mean()),
        "hca_lo": lo, "hca_hi": hi,
        "n_home": int(len(sub)),
    })
per_team_df = pd.DataFrame(per_team).sort_values("hca", ascending=False)

# Pair-adjusted HCA per team
pairs = query("SELECT * FROM feat_pairwise_same_opponent")
pair_hca = pairs.groupby("team_id")["hca_pair_adj"].mean().reset_index(name="hca_pair")


# %% build dashboard
dash = Dashboard(
    title="Phase 4 -- Descriptive HCA",
    slug="phase-04-descriptive",
    subtitle=f"10-season view: league HCA = {league_hca:+.2f} pts over {n_games} games",
)
dash.kpis = [
    {"label": "League HCA", "value": f"{league_hca:+.2f}", "caption": "home margin, pts"},
    {"label": "Home win %", "value": f"{league_home_win*100:.1f}%", "caption": f"of {n_games} games"},
    {"label": "Teams", "value": str(len(per_team_df))},
    {"label": "Seasons", "value": str(fg["season"].nunique()),
     "caption": f"{fg['season'].min()}-{fg['season'].max()}"},
]


# %% D04-1 HCA over time per team (multi-team line chart)
seasons = sorted(fgt["season"].unique())
season_labels = [f"{s}-{str(s+1)[-2:]}" for s in seasons]
league_by_season = home.groupby("season")["point_diff"].mean().reindex(seasons).tolist()

team_datasets = []
for i, (tid, sub) in enumerate(home.groupby("team_id")):
    by_season = sub.groupby("season")["point_diff"].mean().reindex(seasons)
    team_datasets.append({
        "label": team_name.get(tid, tid),
        "data": [None if pd.isna(v) else float(v) for v in by_season.tolist()],
        "color": None,
        "width": 1.5,
        "pointRadius": 2,
    })
# League avg as dashed reference on top
team_datasets.append({
    "label": "league avg",
    "data": [None if pd.isna(v) else float(v) for v in league_by_season],
    "color": "#e7ecf3",
    "width": 3,
    "dash": [6, 4],
    "pointRadius": 0,
})


# %% D04-2 per-team HCA bar with CIs (sorted)
d04_2 = {
    "type": "forest", "id": "D04-2", "title": "Per-team HCA with 95% CI",
    "description": "Home point-differential per team, bootstrap 95% CI.",
    "teams": [
        {"label": r["name"], "mean": r["hca"], "lo": r["hca_lo"], "hi": r["hca_hi"]}
        for _, r in per_team_df.iterrows()
    ],
    "xTitle": "HCA (points)",
    "tall": True, "wide": True,
}


# %% D04-3 team x season heatmap
team_sort = per_team_df["team_id"].tolist()
heatmap_values = []
for tid in team_sort:
    row = []
    for s in seasons:
        m = home[(home["team_id"] == tid) & (home["season"] == s)]["point_diff"]
        row.append(float(m.mean()) if len(m) else None)
    heatmap_values.append(row)

d04_3 = {
    "type": "heatmap", "id": "D04-3", "title": "Team x Season HCA heatmap",
    "description": "Rows sorted by mean HCA. Blue = positive, red = negative.",
    "xs": [str(s) for s in seasons],
    "ys": [team_name.get(t, t) for t in team_sort],
    "values": heatmap_values,
    "wide": True, "tall": True,
}


# %% D04-4 attendance dose-response (game-level)
game_df = home[home["attendance_ratio"].notna()].copy()

# Bin by attendance ratio for LOWESS-like smoothing
bins = np.linspace(0, 1.05, 22)
game_df["ratio_bin"] = pd.cut(game_df["attendance_ratio"], bins, include_lowest=True)
dose_curve = game_df.groupby("ratio_bin", observed=True)["point_diff"].agg(["mean", "count"]).reset_index()
dose_curve["x"] = dose_curve["ratio_bin"].apply(lambda iv: (iv.left + iv.right) / 2)
dose_curve = dose_curve[dose_curve["count"] >= 5]

# Scatter points (sampled to avoid overload)
rng = np.random.default_rng(1)
sample_idx = rng.choice(len(game_df), size=min(2000, len(game_df)), replace=False)
scatter_points = [
    {"x": float(r.attendance_ratio), "y": float(r.point_diff)}
    for r in game_df.iloc[sample_idx].itertuples()
]

d04_4 = {
    "type": "scatter", "id": "D04-4", "title": "Attendance dose-response (game-level)",
    "description": "Home margin vs attendance_ratio. Dots = sampled games. Line = binned mean.",
    "xTitle": "attendance_ratio", "yTitle": "home margin (pts)",
    "datasets": [
        {"label": "games", "data": scatter_points, "color": "#4f8cff", "pointRadius": 2},
    ],
    "trendline": [{"x": float(r.x), "y": float(r["mean"])} for _, r in dose_curve.iterrows()],
    "trendlineLabel": "binned mean (n>=5)",
    "wide": True,
}


# %% D04-5 team-level capacity vs HCA scatter
team_capacity_scatter = []
for _, r in per_team_df.iterrows():
    sub = home[home["team_id"] == r["team_id"]]
    mean_ratio = float(sub["attendance_ratio"].mean()) if sub["attendance_ratio"].notna().any() else None
    if mean_ratio is None:
        continue
    team_capacity_scatter.append({
        "x": mean_ratio, "y": r["hca"], "label": r["name"], "n": int(r["n_home"]),
    })

r_p, p_p = pearson(
    np.array([p["x"] for p in team_capacity_scatter]),
    np.array([p["y"] for p in team_capacity_scatter]),
)
r_s, p_s = spearman(
    np.array([p["x"] for p in team_capacity_scatter]),
    np.array([p["y"] for p in team_capacity_scatter]),
)

d04_5 = {
    "type": "scatter", "id": "D04-5", "title": "Team-level capacity vs HCA",
    "description": (
        f"Each dot = team. Pearson r={r_p:.3f} (p={p_p:.3f}), "
        f"Spearman rho={r_s:.3f} (p={p_s:.3f})."
    ),
    "xTitle": "mean attendance_ratio (home games)", "yTitle": "HCA (pts)",
    "datasets": [{"label": "teams", "data": team_capacity_scatter, "color": "#4ecc8f", "pointRadius": 6}],
    "autoTrend": True,
}


# %% D04-6 season-level capacity vs HCA
season_capacity = home.groupby("season").agg(
    mean_ratio=("attendance_ratio", "mean"),
    hca=("point_diff", "mean"),
    n=("point_diff", "count"),
).reset_index()

season_scatter = [
    {"x": float(r.mean_ratio) if pd.notna(r.mean_ratio) else 0.0,
     "y": float(r.hca), "label": f"{int(r.season)}-{str(int(r.season)+1)[-2:]}",
     "n": int(r.n)}
    for r in season_capacity.itertuples()
]

d04_6 = {
    "type": "scatter", "id": "D04-6", "title": "Season-level capacity vs HCA",
    "description": "One dot per season. 2020-21 is the closed-doors left endpoint.",
    "xTitle": "league mean attendance_ratio", "yTitle": "league HCA (pts)",
    "datasets": [{"label": "seasons", "data": season_scatter, "color": "#f5c264", "pointRadius": 8}],
    "autoTrend": True,
}


# %% D04-7 bump chart: team rank by HCA across seasons
rank_rows = []
for s in seasons:
    season_home = home[home["season"] == s]
    ranks = season_home.groupby("team_id")["point_diff"].mean().rank(ascending=False)
    for tid, r in ranks.items():
        rank_rows.append({"season": s, "team_id": tid, "rank": float(r)})
rank_df = pd.DataFrame(rank_rows)

bump_datasets = []
for tid in per_team_df["team_id"].tolist():
    ranks_by_season = rank_df[rank_df["team_id"] == tid].set_index("season")["rank"]
    bump_datasets.append({
        "label": team_name.get(tid, tid),
        "data": [float(ranks_by_season.get(s, None)) if not pd.isna(ranks_by_season.get(s, float('nan'))) else None for s in seasons],
        "width": 1.5,
    })

d04_7 = {
    "type": "line", "id": "D04-7", "title": "Team rank by HCA over seasons",
    "description": "Rank 1 = highest HCA that season.",
    "labels": season_labels,
    "datasets": bump_datasets,
    "yTitle": "rank (1 = highest HCA)", "xTitle": "season",
    "wide": True, "tall": True,
}


# %% D04-8 home vs away PPG per team (dual-line)
ppg_rows = []
for tid in per_team_df["team_id"].tolist():
    h = fgt[(fgt["team_id"] == tid) & (fgt["is_home"] == 1)]
    a = fgt[(fgt["team_id"] == tid) & (fgt["is_home"] == 0)]
    ppg_rows.append({
        "team_id": tid, "name": team_name.get(tid, tid),
        "home_pts": float(h["team_pts"].mean()),
        "away_pts": float(a["team_pts"].mean()),
        "home_allowed": float(h["opp_pts"].mean()),
        "away_allowed": float(a["opp_pts"].mean()),
    })
ppg_df = pd.DataFrame(ppg_rows)
ppg_df["off_edge"] = ppg_df["home_pts"] - ppg_df["away_pts"]
ppg_df["def_edge"] = ppg_df["away_allowed"] - ppg_df["home_allowed"]

d04_8 = {
    "type": "bar", "id": "D04-8", "title": "Home-vs-away scoring edges per team (pts)",
    "description": "Offensive edge = home PPG - away PPG. Defensive edge = away PPG allowed - home PPG allowed.",
    "labels": ppg_df["name"].tolist(),
    "datasets": [
        {"label": "offensive edge", "data": ppg_df["off_edge"].round(2).tolist()},
        {"label": "defensive edge", "data": ppg_df["def_edge"].round(2).tolist()},
    ],
    "yTitle": "pts", "wide": True, "horizontal": False,
}


# %% D04-9 regular vs playoff HCA per team (paired bars)
rs_vs_po = home.groupby(["team_id", "phase"])["point_diff"].mean().unstack("phase")
rs_vs_po = rs_vs_po.reindex(per_team_df["team_id"].tolist())

d04_9 = {
    "type": "bar", "id": "D04-9", "title": "Regular season vs playoff HCA per team",
    "description": "H3 visual: does HCA shrink in playoffs?",
    "labels": [team_name.get(t, t) for t in rs_vs_po.index.tolist()],
    "datasets": [
        {"label": "regular season", "data": [float(v) if pd.notna(v) else None for v in rs_vs_po.get("RS", pd.Series()).tolist()]},
        {"label": "playoffs", "data": [float(v) if pd.notna(v) else None for v in rs_vs_po.get("PO", pd.Series()).tolist()]},
    ],
    "yTitle": "HCA (pts)", "wide": True,
}


# %% D04-10 attendance distribution boxplot per team (approximated as percentile lines)
att_per_team = []
for tid in per_team_df["team_id"].tolist():
    vals = home[(home["team_id"] == tid)]["attendance_ratio"].dropna().values
    if len(vals) == 0:
        continue
    att_per_team.append({
        "team_id": tid, "name": team_name.get(tid, tid),
        "p25": float(np.percentile(vals, 25)),
        "median": float(np.percentile(vals, 50)),
        "p75": float(np.percentile(vals, 75)),
        "min": float(np.min(vals)), "max": float(np.max(vals)),
    })
att_per_team.sort(key=lambda r: r["median"], reverse=True)

d04_10 = {
    "type": "bar", "id": "D04-10",
    "title": "Attendance distribution per team (P25 / median / P75)",
    "description": "Median fullness and interquartile range per arena.",
    "labels": [r["name"] for r in att_per_team],
    "datasets": [
        {"label": "P25", "data": [r["p25"] for r in att_per_team]},
        {"label": "median", "data": [r["median"] for r in att_per_team]},
        {"label": "P75", "data": [r["p75"] for r in att_per_team]},
    ],
    "yTitle": "attendance_ratio", "wide": True,
}


# %% D04-11 attendance calendar heatmap (pick one representative team-season)
rep_team = per_team_df["team_id"].iloc[0]
rep_name = team_name.get(rep_team, rep_team)
rep_season = max(seasons)
rep_df = home[(home["team_id"] == rep_team) & (home["season"] == rep_season)].copy()
rep_df["date_str"] = pd.to_datetime(rep_df["date"]).dt.strftime("%b-%d")

d04_11 = {
    "type": "bar", "id": "D04-11",
    "title": f"Attendance calendar for {rep_name}, {rep_season}-{str(rep_season+1)[-2:]}",
    "description": "One bar per home game, height = attendance_ratio.",
    "labels": rep_df["date_str"].tolist(),
    "datasets": [{"label": "attendance_ratio", "data": rep_df["attendance_ratio"].round(3).tolist()}],
    "yTitle": "attendance_ratio", "wide": True,
}


# %% D04-12 biggest HCA upsets table (home lost by most vs Elo expectation)
upsets = home.copy()
# Elo-predicted margin: (team_elo - opp_elo) / 28 from our Elo. HCA not baked in.
upsets["elo_expected"] = (upsets["team_elo_pre"] - upsets["opp_elo_pre"]) / 28.0
upsets["residual"] = upsets["point_diff"] - upsets["elo_expected"]
upsets = upsets.sort_values("residual").head(20)

d04_12 = {
    "type": "table", "id": "D04-12",
    "title": "Biggest HCA upsets (home lost vs Elo expectation)",
    "description": "Residual = actual home margin - Elo-expected margin. Most-negative = biggest upsets.",
    "columns": ["date", "home", "away", "margin", "elo-expected", "residual"],
    "rows": [
        [str(r.date.date()), team_name.get(r.team_id, r.team_id), team_name.get(r.opp_team_id, r.opp_team_id),
         f"{r.point_diff:+d}", f"{r.elo_expected:+.1f}", f"{r.residual:+.2f}"]
        for r in upsets.itertuples()
    ],
    "wide": True,
}


# %% D04-13 HCA vs Elo scatter per team-season
elo_hca = []
for (tid, s), sub in home.groupby(["team_id", "season"]):
    hca_s = float(sub["point_diff"].mean())
    elo_s = float(sub["team_elo_pre"].mean())
    elo_hca.append({"x": elo_s, "y": hca_s, "label": f"{team_name.get(tid, tid)} {s}"})

d04_13 = {
    "type": "scatter", "id": "D04-13", "title": "HCA vs team-season mean Elo",
    "description": "Are stronger teams better at home?",
    "xTitle": "mean team Elo", "yTitle": "HCA (pts)",
    "datasets": [{"label": "team-season", "data": elo_hca, "color": "#b58bff", "pointRadius": 3}],
    "autoTrend": True,
}


# %% D04-14 home-margin histogram
margins = fg["home_margin"].values
hist, edges = np.histogram(margins, bins=40)
centers = (edges[:-1] + edges[1:]) / 2

d04_14 = {
    "type": "bar", "id": "D04-14", "title": "Home-margin histogram (all games)",
    "description": f"Mean = {np.mean(margins):+.2f}, median = {np.median(margins):+.1f}.",
    "labels": [f"{int(c)}" for c in centers],
    "datasets": [{"label": "games", "data": hist.astype(int).tolist(), "color": "#7bd8dd"}],
    "xTitle": "home_margin (pts)", "yTitle": "# games", "wide": True,
}


# %% D04-15 HCA by weekday / month
fgt["weekday"] = fgt["date"].dt.day_name()
fgt["month"] = fgt["date"].dt.month_name()
weekday_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
wd = fgt[fgt["is_home"] == 1].groupby("weekday")["point_diff"].mean().reindex(weekday_order)

d04_15 = {
    "type": "bar", "id": "D04-15", "title": "HCA by weekday",
    "description": "Home point-differential by day of week.",
    "labels": weekday_order,
    "datasets": [{"label": "HCA (pts)", "data": [float(v) if pd.notna(v) else None for v in wd.tolist()]}],
    "yTitle": "HCA (pts)",
}


# %% D04-16 streak length distribution (home and away runs)
fg_sorted = fg.sort_values(["season", "date"])
runs = []
for s, sub in fg_sorted.groupby("season"):
    # per team, count consecutive home or away games in sub
    for tid in per_team_df["team_id"].tolist():
        mask_home = sub[sub["home_team_id"] == tid]
        mask_away = sub[sub["away_team_id"] == tid]
        team_games = pd.concat([
            mask_home.assign(is_home=1),
            mask_away.assign(is_home=0),
        ]).sort_values("date")
        if len(team_games) == 0:
            continue
        run_len = 1
        for i in range(1, len(team_games)):
            if team_games.iloc[i]["is_home"] == team_games.iloc[i - 1]["is_home"]:
                run_len += 1
            else:
                runs.append(run_len)
                run_len = 1
        runs.append(run_len)

import collections
run_counts = collections.Counter(runs)
max_run = max(run_counts.keys()) if run_counts else 1

d04_16 = {
    "type": "bar", "id": "D04-16", "title": "Home/away streak length distribution",
    "description": "Consecutive games with the same venue type.",
    "labels": [str(k) for k in range(1, max_run + 1)],
    "datasets": [{"label": "# streaks", "data": [int(run_counts.get(k, 0)) for k in range(1, max_run + 1)]}],
    "xTitle": "streak length (games)", "yTitle": "# occurrences",
}


# %% assemble sections
core_charts = [
    {
        "type": "line", "id": "D04-1", "title": "HCA over time, per team", "wide": True, "tall": True,
        "description": "X = season, Y = mean home margin. Thin colored lines = teams; thick dashed = league average.",
        "labels": season_labels,
        "datasets": team_datasets,
        "yTitle": "HCA (pts)", "xTitle": "season",
        "legend": True,
    },
    d04_2,
    d04_3,
    d04_7,
    d04_8,
    d04_9,
    d04_14,
    d04_15,
    d04_16,
    d04_13,
    d04_12,
]

attendance_charts = [
    d04_4, d04_5, d04_6, d04_10, d04_11,
]

dash.add_section("core", "Core HCA", "League-wide and per-team headline views.", charts=core_charts)
dash.add_section(
    "attendance", "Capacity / attendance",
    "Three complementary capacity-vs-HCA views + distributions.",
    charts=attendance_charts,
)

out = dash.write()
print(f"dashboard: {out}")
print(f"league HCA: {league_hca:+.3f} pts | home win%: {league_home_win*100:.1f}% | n={n_games}")
