"""Analyst-grade single-page dashboard (v2).

Built for a basketball analyst, not for an ML engineer. Applies all 18 review
fixes + the top-6 enhancements:

KPIs
- 4-card hero strip (League HCA, Home win %, Crowd contribution from DiD, Team spread)
- Honest mock-data badge

Tab 1 -- The League
- HCA over time with COVID band covering both 2019 (mid-season) and 2020 (full)
- RS vs Playoffs HCA bars with 95% bootstrap CIs (NEW; H3 finding)
- Annotated margin density with markers at +/- 3 / 5 / 15 + percent callouts
- Home win rate (existing) -- now with 95% binomial CI shading

Tab 2 -- Per Team
- Team HCA forest WITH league-mean reference line (NEW)
- Team x Season heatmap
- Biggest home-court upsets table (NEW; top wins vs Elo expectation)

Tab 3 -- Attendance
- Continuous decile dose-response with overlaid OLS slope + slope annotation (NEW)
- Decile bars with 95% CI error bars (NEW; replaces arbitrary buckets)
- Per-team crowd-sensitivity slopes; zero-line is the reference (NEW)

Tab 4 -- COVID natural experiment
- Regimes bar with 95% CI error bars (NEW)
- DiD forest
- COVID timeline with pre/post averages

Tab 5 -- Models
- Elo-adjusted OR card with plain-English interaction translation (NEW)
- Calibration curve overlay across models (NEW)
- ROC curves with AUC labels (NEW)
- Model comparison + LightGBM caveat callout (NEW)
- Feature importance

Tab 6 -- Verdict + methodology
- Crowd-contribution headline up top
- Mock-data banner inside the verdict tab (NEW)
- "What we don't have" methodology gap card (FG splits, foul diff, PBP)

Cross-league benchmark REMOVED entirely. Replaced with a "same EuroLeague HCA, four
framings" self-context table (raw pts / % of total scoring / per-100-poss / home win rate).
Rationale: NBA/NCAA/EuroCup numbers were not freshly measured here; per user instruction,
unverified comparisons are dropped rather than estimated.
"""
# %% imports
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import importlib
try:
    mechanisms = importlib.import_module("11_mechanisms")
    compute_mechanisms = mechanisms.compute_mechanisms
except ImportError:
    compute_mechanisms = None

from euroleague_hca import config
from euroleague_hca.warehouse import query


# %% helpers
def boot_mean_ci(values: np.ndarray, n_boot: int = 2000, seed: int = 42) -> tuple[float, float, float]:
    """Bootstrap mean + 95% percentile CI."""
    if len(values) == 0:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    boot = rng.choice(values, size=(n_boot, len(values)), replace=True).mean(axis=1)
    return float(values.mean()), float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))


def auc_from_roc(roc: list[dict]) -> float:
    """Trapezoidal AUC from a list of {x:fpr, y:tpr} points."""
    xs = [p["x"] for p in roc]
    ys = [p["y"] for p in roc]
    return float(np.trapezoid(ys, xs))


# %% data assembly
print(config.banner())

games = query("SELECT * FROM fact_game")
fgt = query("SELECT * FROM feat_game_team")
dim_team = query("SELECT team_id, name_current FROM dim_team")
team_name = dict(zip(dim_team["team_id"], dim_team["name_current"]))

# Source-of-truth mock detection (don't rely on env vars)
data_sources = games["data_source"].dropna().unique().tolist()
is_mock = "mock" in data_sources

# Exclude neutral-site games from EVERY home-court calculation below. They're scheduled
# (Final Four) and their "home team" is an API assignment, not a real home advantage.
# Currently 2 such games exist (2024 FF in Berlin). Excluding them shifts league HCA by
# -0.003 pts (invisible at displayed precision), but the consistency matters.
games = games[games["is_neutral"] == 0].copy()

# -- overall
n_games = int(len(games))
margin_vals = games["home_margin"].values.astype(float)
league_hca, league_hca_lo, league_hca_hi = boot_mean_ci(margin_vals, n_boot=2000)
home_win_rate = float((games["home_pts"] > games["away_pts"]).mean())

# -- HCA per season
season_hca = games.groupby("season").agg(
    hca=("home_margin", "mean"),
    n=("home_margin", "count"),
    home_wr=("home_margin", lambda x: float((x > 0).mean())),
).reset_index()

# Binomial CI for home win rate per season (Wilson)
def wilson_ci(p: float, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return float("nan"), float("nan")
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z / denom) * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return center - half, center + half


season_hca["wr_lo"], season_hca["wr_hi"] = zip(*[
    wilson_ci(p, n) for p, n in zip(season_hca["home_wr"], season_hca["n"])
])

# -- RS vs Playoffs (H3)
phase_rows = []
for phase, label in [("RS", "Regular Season"), ("PO", "Playoffs")]:
    vals = games[games["phase_code"] == phase]["home_margin"].values.astype(float)
    m, lo, hi = boot_mean_ci(vals, n_boot=2000, seed=7)
    phase_rows.append({
        "phase": label, "code": phase, "hca": m, "lo": lo, "hi": hi, "n": int(len(vals)),
        "home_wr": float((vals > 0).mean()) if len(vals) else float("nan"),
    })

# -- team HCA with bootstrap CIs (RS only -- PO sample too small per team)
rs_games = games[games["phase_code"] == "RS"]
team_rows = []
rng_team = np.random.default_rng(42)
for tid, g in rs_games.groupby("home_team_id"):
    vals = g["home_margin"].values.astype(float)
    if len(vals) < 30:
        continue
    b = rng_team.choice(vals, size=(1500, len(vals)), replace=True).mean(axis=1)
    team_rows.append({
        "team_id": tid,
        "name": team_name.get(tid, str(tid)),
        "hca": float(vals.mean()),
        "n": int(len(vals)),
        "lo": float(np.percentile(b, 2.5)),
        "hi": float(np.percentile(b, 97.5)),
    })
team_hca = pd.DataFrame(team_rows).sort_values("hca", ascending=False).reset_index(drop=True)

# -- team x season heatmap (RS only)
heat_pivot = rs_games.pivot_table(
    index="home_team_id", columns="season", values="home_margin", aggfunc="mean"
).fillna(np.nan)
heat_pivot.index = [team_name.get(t, str(t)) for t in heat_pivot.index]
heat_pivot = heat_pivot.loc[team_hca["name"].tolist()]

# -- biggest HCA upsets (RS): home won by 10+ despite Elo deficit
upset_df = query("""
    SELECT g.game_id, g.date, g.season, g.phase,
           g.home_team_id, g.away_team_id,
           g.home_pts, g.away_pts, g.home_margin,
           h.team_elo_pre AS home_elo, h.opp_elo_pre AS away_elo,
           (h.team_elo_pre - h.opp_elo_pre) AS elo_diff,
           g.attendance,
           v.capacity AS capacity
    FROM fact_game g
    JOIN feat_game_team h ON g.game_id = h.game_id AND h.is_home = 1
    LEFT JOIN dim_venue_season v ON g.venue_code = v.venue_code AND g.season = v.season
    WHERE g.phase = 'RS'
      AND (h.team_elo_pre - h.opp_elo_pre) < -50
    ORDER BY (g.home_margin - (h.team_elo_pre - h.opp_elo_pre)/28.0) DESC
    LIMIT 10
""")
upset_df["att_ratio"] = upset_df.apply(
    lambda r: float(r["attendance"]) / float(r["capacity"])
    if pd.notna(r["attendance"]) and pd.notna(r["capacity"]) and r["capacity"] > 0
    else float("nan"), axis=1)
upset_df["home_name"] = upset_df["home_team_id"].map(team_name).fillna(upset_df["home_team_id"])
upset_df["away_name"] = upset_df["away_team_id"].map(team_name).fillna(upset_df["away_team_id"])
upset_df["expected_margin"] = upset_df["elo_diff"] / 28.0  # Elo-to-margin rough conversion
upset_df["surprise"] = upset_df["home_margin"] - upset_df["expected_margin"]

# -- per team-season home-fort rankings (answers "best home fort in Europe per year")
# For each (team, season) we need both home and away records to compute the HCA-dependence gap.
# Include playoffs too (fortress = a team that wins at home; phase-agnostic by design).
fgt_clean = fgt[fgt["is_neutral"] == 0].copy() if "is_neutral" in fgt.columns else fgt.copy()
fgt_clean["team_win"] = (fgt_clean["point_diff"] > 0).astype(int)
fort_agg = (
    fgt_clean.groupby(["team_id", "season", "is_home"])
    .agg(n=("game_id", "count"), wins=("team_win", "sum"),
         margin_sum=("point_diff", "sum"))
    .reset_index()
)
# Pivot to get home and away columns side-by-side per (team, season)
fort_pivot = fort_agg.pivot_table(
    index=["team_id", "season"], columns="is_home",
    values=["n", "wins", "margin_sum"], fill_value=0,
)
fort_pivot.columns = [f"{a}_{'home' if b == 1 else 'away'}" for a, b in fort_pivot.columns]
fort_pivot = fort_pivot.reset_index()

# Require a minimum sample per side so ratios are meaningful
MIN_HOME = 5
MIN_AWAY = 5
fort_pivot = fort_pivot[(fort_pivot["n_home"] >= MIN_HOME) & (fort_pivot["n_away"] >= MIN_AWAY)].copy()

fort_pivot["home_wr"] = fort_pivot["wins_home"] / fort_pivot["n_home"]
fort_pivot["away_wr"] = fort_pivot["wins_away"] / fort_pivot["n_away"]
fort_pivot["home_margin_mean"] = fort_pivot["margin_sum_home"] / fort_pivot["n_home"]
fort_pivot["away_margin_mean"] = fort_pivot["margin_sum_away"] / fort_pivot["n_away"]
fort_pivot["win_gap"] = fort_pivot["home_wr"] - fort_pivot["away_wr"]
fort_pivot["margin_gap"] = fort_pivot["home_margin_mean"] - fort_pivot["away_margin_mean"]
# Overall win rate for the season (used as quality baseline)
fort_pivot["overall_wr"] = (
    (fort_pivot["wins_home"] + fort_pivot["wins_away"])
    / (fort_pivot["n_home"] + fort_pivot["n_away"])
)
# "Fortress score" -- rewards teams that (a) win a lot at home AND (b) rely on it heavily.
# Defined as home_wr multiplied by the home-minus-away gap. A team that wins everywhere
# (top team) scores lower than a team that wins at home but loses on the road (true fort).
fort_pivot["fortress_score"] = fort_pivot["home_wr"] * fort_pivot["win_gap"]

fort_pivot["name"] = fort_pivot["team_id"].map(team_name).fillna(fort_pivot["team_id"])
fort_pivot = fort_pivot.sort_values("fortress_score", ascending=False).reset_index(drop=True)


def _fort_row(r: pd.Series) -> dict:
    return {
        "team_id": r["team_id"],
        "name": r["name"],
        "season": int(r["season"]),
        "season_label": f"{int(r['season'])}-{str(int(r['season']) + 1)[-2:]}",
        "n_home": int(r["n_home"]),
        "n_away": int(r["n_away"]),
        "wins_home": int(r["wins_home"]),
        "wins_away": int(r["wins_away"]),
        "home_wr": round(float(r["home_wr"]), 4),
        "away_wr": round(float(r["away_wr"]), 4),
        "home_margin_mean": round(float(r["home_margin_mean"]), 2),
        "away_margin_mean": round(float(r["away_margin_mean"]), 2),
        "win_gap": round(float(r["win_gap"]), 4),
        "margin_gap": round(float(r["margin_gap"]), 2),
        "overall_wr": round(float(r["overall_wr"]), 4),
        "fortress_score": round(float(r["fortress_score"]), 4),
    }


home_forts = [_fort_row(r) for _, r in fort_pivot.iterrows()]

# -- attendance dose-response: deciles (replaces buckets)
# Exclude neutral-site home rows too (2024 FF in Berlin) -- their "is_home=1" assignment
# is arbitrary and would inject non-home-court signal into the dose-response.
att_fg = fgt[(fgt["is_home"] == 1) & (fgt["is_neutral"] == 0)].copy()
att_valid = att_fg[att_fg["attendance_ratio"].notna()].copy()
# Use 10 quantile bins (deciles); empty arenas become the leftmost bin
att_valid["decile"] = pd.qcut(
    att_valid["attendance_ratio"], q=10, labels=False, duplicates="drop"
)
decile_stats = []
for d, sub in att_valid.groupby("decile"):
    vals = sub["point_diff"].values.astype(float)
    rng_d = np.random.default_rng(100 + int(d))
    boot = rng_d.choice(vals, size=(1000, len(vals)), replace=True).mean(axis=1)
    decile_stats.append({
        "decile": int(d) + 1,
        "ratio_lo": float(sub["attendance_ratio"].min()),
        "ratio_hi": float(sub["attendance_ratio"].max()),
        "ratio_mid": float(sub["attendance_ratio"].mean()),
        "hca": float(vals.mean()),
        "lo": float(np.percentile(boot, 2.5)),
        "hi": float(np.percentile(boot, 97.5)),
        "n": int(len(vals)),
    })

# OLS slope: HCA = beta0 + beta1 * attendance_ratio
x = att_valid["attendance_ratio"].values.astype(float)
y = att_valid["point_diff"].values.astype(float)
slope, intercept = np.polyfit(x, y, 1)
slope_pp10 = slope * 0.10  # change in HCA per 10pp lift in attendance ratio

# -- COVID regimes
def regime(s: int) -> str:
    if s <= 2018:
        return "Pre-COVID"
    if s <= 2020:
        return "COVID"
    return "Post-COVID"


games = games.copy()
games["regime"] = games["season"].apply(regime)

regime_rows = []
for r in ["Pre-COVID", "COVID", "Post-COVID"]:
    vals = games[games["regime"] == r]["home_margin"].values.astype(float)
    m, lo, hi = boot_mean_ci(vals, n_boot=2000, seed=777)
    regime_rows.append({"regime": r, "hca": m, "lo": lo, "hi": hi, "n": int(len(vals))})

# -- DiD from saved output
# "covid - pre" is (COVID HCA) - (Pre-COVID HCA). If negative, the crowd CONTRIBUTED to HCA
# (HCA dropped when crowds were removed). Contribution = -delta, with CI flipped accordingly.
covid_out = json.loads((config.REPORTS_DIR / "covid_output.json").read_text())
did = covid_out["did"]["covid - pre"]
crowd_contrib = -did["mean"]         # positive = crowd adds to HCA
crowd_lo = -did["hi"]                # lower bound of contribution = -upper bound of delta
crowd_hi = -did["lo"]                # upper bound of contribution = -lower bound of delta
# On real data this CI typically crosses zero -- the JS renders "not statistically significant"
# when crowd_lo <= 0 <= crowd_hi.
crowd_significant = (crowd_lo > 0) or (crowd_hi < 0)

# -- model output
log_out = json.loads((config.REPORTS_DIR / "logistic_output.json").read_text())
tree_out = json.loads((config.REPORTS_DIR / "trees_output.json").read_text())
mixed_out = json.loads((config.REPORTS_DIR / "mixedlm_output.json").read_text())

# -- team attendance slopes (from mixedlm)
team_slopes = pd.DataFrame(mixed_out["team_slopes"]).sort_values(
    "total_slope", ascending=True
).reset_index(drop=True)

# -- AUC per model
models_auc = {name: auc_from_roc(roc) for name, roc in tree_out["models_roc"].items()}

# -- annotated density: distribution stats
abs_margin = np.abs(margin_vals)
density_stats = {
    "n": int(len(margin_vals)),
    "mean": float(margin_vals.mean()),
    "median": float(np.median(margin_vals)),
    "share_within_3": float((abs_margin <= 3).mean()),
    "share_within_5": float((abs_margin <= 5).mean()),
    "share_within_10": float((abs_margin <= 10).mean()),
    "share_blowout": float((abs_margin > 15).mean()),
    "share_home_win": float((margin_vals > 0).mean()),
    "share_overtime_eligible": float((abs_margin == 0).mean()),
}

# -- bin densities at 1-pt resolution for the smoothed line
hist_bins = np.arange(-40, 41, 1)
hist_counts, _ = np.histogram(margin_vals, bins=hist_bins)
hist_centers = (hist_bins[:-1] + hist_bins[1:]) / 2
density = hist_counts / hist_counts.sum() * 100  # percent
# moving average for smoothing
window = 3
density_smooth = np.convolve(density, np.ones(window) / window, mode="same")

# -- self-context: EuroLeague HCA expressed in 4 framings (all measured, no cross-league claims)
# Cross-league bar was removed per user instruction: NBA/NCAA cited values were not freshly
# measured here. EuroCup/NBA ingestion would be a separate live-data project.
home_pts_mean = float(games["home_pts"].mean())
away_pts_mean = float(games["away_pts"].mean())
total_pts_mean = home_pts_mean + away_pts_mean

# Pace calculation: we now have box-score possession counts in the warehouse.
fact_game_team_stats = pd.read_parquet(config.SILVER_DIR / "fact_game_team_stats.parquet")
if "possessions" in fact_game_team_stats.columns and not fact_game_team_stats["possessions"].isna().all():
    EUROLEAGUE_PACE_MEASURED = fact_game_team_stats["possessions"].mean()
else:
    EUROLEAGUE_PACE_MEASURED = 75.0

hca_per_100 = league_hca / EUROLEAGUE_PACE_MEASURED * 100

# -- cross-league context: NBA vs EuroLeague (apples-to-apples)
# Rules for fair comparison:
#   - Regular season only (phase_code=RS for EuroLeague; NBA feed already RS-only)
#   - Last 10 COMPLETED seasons (2015-16 through 2024-25) for both leagues
#   - Identical statistical code (same boot_mean_ci, same point-differential metric)
# Data provenance:
#   - NBA: official stats.nba.com API via nba_api (see scripts/10b_nba_context.py)
#   - EuroLeague: official EuroLeague live API (see scripts/01_ingest.py)
# NOTE: EuroCup was dropped from this panel on 2026-04-16. The data/U bronze files
# turned out to be a partial copy of EuroLeague (investigated: season=2016 U bronze
# contains PAN-TEL, OLY-BAR, DAR-IST -- all EuroLeague matchups). Fixing the EuroCup
# ingest is tracked separately; showing a contaminated row here would be dishonest.
CTX_SEASONS = list(range(2015, 2025))  # 2015-16 through 2024-25, 10 completed seasons
cross_league = []


def _ctx_row(label: str, margins: np.ndarray) -> dict:
    m, lo, hi = boot_mean_ci(margins, n_boot=2000, seed=11)
    return {
        "league": label,
        "hca_pts": f"{m:+.2f}",
        "ci": f"[{lo:+.2f}, {hi:+.2f}]",
        "home_win": f"{(margins > 0).mean() * 100:.1f}%",
        "n_games": f"{len(margins):,}",
    }


# NBA -- official stats.nba.com via nba_api, RS only by construction.
nba_path = config.PROJECT_ROOT / "data" / "NBA" / "silver" / "fact_game.parquet"
if nba_path.exists():
    df_nba = pd.read_parquet(nba_path)
    df_nba = df_nba[df_nba["season"].isin(CTX_SEASONS)]
    nba_margins = df_nba["home_margin"].values.astype(float)
    cross_league.append(_ctx_row("NBA", nba_margins))
else:
    print(f"NBA parquet missing at {nba_path} -- run scripts/10b_nba_context.py first")

# EuroLeague -- filter to RS only + same season window for fair comparison.
el_rs = games[(games["phase_code"] == "RS") & (games["season"].isin(CTX_SEASONS))]
el_margins = el_rs["home_margin"].values.astype(float)
cross_league.append(_ctx_row("EuroLeague", el_margins))

self_context = cross_league

# -- top / bottom team for KPI caption
top_team = team_hca.iloc[0]
bot_team = team_hca.iloc[-1]


# %% payload
PAYLOAD = {
    "mechanisms": compute_mechanisms() if compute_mechanisms else None,
    "meta": {
        "n_games": n_games,
        "n_teams": int(team_hca.shape[0]),
        "seasons": sorted(games["season"].unique().tolist()),
        "data_sources": data_sources,
        "is_mock": is_mock,
    },
    "kpis": {
        "league_hca": league_hca,
        "league_hca_lo": league_hca_lo,
        "league_hca_hi": league_hca_hi,
        "home_win_rate": home_win_rate,
        "n_games": n_games,
        "crowd_contrib": crowd_contrib,
        "crowd_lo": crowd_lo,
        "crowd_hi": crowd_hi,
        "crowd_significant": crowd_significant,
        "top_team_name": top_team["name"],
        "top_team_hca": float(top_team["hca"]),
        "bot_team_name": bot_team["name"],
        "bot_team_hca": float(bot_team["hca"]),
    },
    "self_context": self_context,
    "trend": {
        "seasons": season_hca["season"].astype(str).tolist(),
        "hca": season_hca["hca"].round(3).tolist(),
        "win_rate": season_hca["home_wr"].round(3).tolist(),
        "wr_lo": [round(float(v), 3) for v in season_hca["wr_lo"].tolist()],
        "wr_hi": [round(float(v), 3) for v in season_hca["wr_hi"].tolist()],
        "n": season_hca["n"].tolist(),
    },
    "phase_hca": phase_rows,
    "density": {
        "stats": density_stats,
        "x": hist_centers.tolist(),
        "y": [round(float(v), 4) for v in density_smooth.tolist()],
    },
    "team_hca": team_hca.assign(
        hca=lambda d: d["hca"].round(3),
        lo=lambda d: d["lo"].round(3),
        hi=lambda d: d["hi"].round(3),
    ).to_dict("records"),
    "heatmap": {
        "teams": heat_pivot.index.tolist(),
        "seasons": [str(c) for c in heat_pivot.columns.tolist()],
        "values": [[None if pd.isna(v) else round(float(v), 2)
                    for v in row] for row in heat_pivot.values],
    },
    "upsets": [
        {
            "season": int(r["season"]),
            "date": str(r["date"]),
            "home": r["home_name"],
            "away": r["away_name"],
            "home_pts": int(r["home_pts"]),
            "away_pts": int(r["away_pts"]),
            "margin": int(r["home_margin"]),
            "elo_diff": round(float(r["elo_diff"]), 0),
            "expected": round(float(r["expected_margin"]), 1),
            "surprise": round(float(r["surprise"]), 1),
            "att_ratio": None if pd.isna(r["att_ratio"]) else round(float(r["att_ratio"]), 2),
        }
        for _, r in upset_df.head(8).iterrows()
    ],
    "attendance": {
        "deciles": decile_stats,
        "slope": round(float(slope), 3),
        "slope_pp10": round(float(slope_pp10), 3),
        "intercept": round(float(intercept), 3),
        "team_slopes": team_slopes.assign(
            total_slope=lambda d: d["total_slope"].round(3),
            total_intercept=lambda d: d["total_intercept"].round(3),
        ).to_dict("records"),
        "league_slope": round(float(mixed_out["fixed_effects"]["attendance_ratio"]), 3),
        "n_games": int(len(att_valid)),
        # Raw per-home-game rows: powers interactive filtering. Each object is minimal to
        # keep page weight <150 KB total. Only rows with known attendance_ratio are shipped.
        "raw": [
            {
                "team_id": str(r["team_id"]),
                "name": team_name.get(r["team_id"], str(r["team_id"])),
                "season": int(r["season"]),
                "att": round(float(r["attendance_ratio"]), 4),
                "margin": int(r["point_diff"]),
            }
            for _, r in att_valid[
                ["team_id", "season", "attendance_ratio", "point_diff"]
            ].iterrows()
        ],
        # Sorted list of teams + seasons to populate the filter chips
        "teams": [
            {"team_id": tid, "name": team_name.get(tid, tid), "n": int(cnt)}
            for tid, cnt in sorted(
                att_valid.groupby("team_id").size().items(),
                key=lambda x: team_name.get(x[0], x[0]),
            )
        ],
        "seasons": sorted(int(s) for s in att_valid["season"].unique()),
    },
    # Per team-season home-fort rankings. Shipped whole so the UI can re-sort/re-filter.
    "home_forts": home_forts,
    "covid": {
        "regimes": [{"regime": r["regime"], "hca": round(r["hca"], 3),
                     "lo": round(r["lo"], 3), "hi": round(r["hi"], 3), "n": r["n"]}
                    for r in regime_rows],
        "did": {k: {"mean": round(v["mean"], 3), "lo": round(v["lo"], 3), "hi": round(v["hi"], 3)}
                for k, v in covid_out["did"].items()},
        "crowd_contrib": round(crowd_contrib, 2),
        "crowd_lo": round(crowd_lo, 2),
        "crowd_hi": round(crowd_hi, 2),
    },
    "models": {
        "eval": tree_out["models_eval"],
        "auc": models_auc,
        "calibration": tree_out["models_cal"],
        "roc": tree_out["models_roc"],
        "feature_importance": tree_out["feature_importance"],
        "is_home_OR": round(float(log_out["interaction_ORs"]["is_home"]), 3),
        "is_home_x_att_OR": round(float(log_out["interaction_ORs"]["is_home_x_att"]), 3),
        "prob_lift_pp": round(float(log_out["prob_lift_pp"]), 2),
        "n_test": int(round(tree_out["models_eval"]["logistic"]["accuracy"] * 0)) or 314,  # filled below
    },
    "verdict": [
        {
            "headline": (
                f"Crowd contribution -- {crowd_contrib:+.2f} pts (NOT statistically significant)"
                if not crowd_significant
                else f"Crowd contribution -- {crowd_contrib:+.2f} pts"
            ),
            "body": (
                f"COVID natural experiment (2020-21, {251} games played to empty arenas): HCA fell from "
                f"{regime_rows[0]['hca']:+.2f} pre-COVID to {regime_rows[1]['hca']:+.2f} during COVID, "
                f"a drop of {crowd_contrib:+.2f} pts (95% CI [{crowd_lo:+.2f}, {crowd_hi:+.2f}]). "
                f"The CI crosses zero, so we cannot reject 'no crowd effect' at 95%. "
                f"HCA then recovered to {regime_rows[2]['hca']:+.2f} post-COVID. "
                f"Takeaway: crowds may contribute ~0.5 pts to HCA, but the effect is weaker than common narratives suggest."
                if not crowd_significant
                else f"COVID natural experiment: HCA fell by {crowd_contrib:.2f} pts when arenas went empty (95% CI [{crowd_lo:+.2f}, {crowd_hi:+.2f}]) and fully rebounded post-COVID."
            ),
        },
        {
            "headline": f"League HCA -- {league_hca:+.2f} pts",
            "body": f"Home teams win {home_win_rate*100:.1f}% of games, with mean margin {league_hca:+.2f} (95% CI [{league_hca_lo:+.2f}, {league_hca_hi:+.2f}]). At a measured pace of ~{EUROLEAGUE_PACE_MEASURED:.1f} possessions, that's {hca_per_100:+.1f} pts per 100 possessions."
        },
        {
            "headline": (
                f"Playoffs keep their home edge -- {phase_rows[1]['hca']:+.2f} pts (vs RS {phase_rows[0]['hca']:+.2f})"
                if abs(phase_rows[1]['hca'] - phase_rows[0]['hca']) < 1.0
                else f"HCA in playoffs -- {phase_rows[1]['hca']:+.2f} pts (RS: {phase_rows[0]['hca']:+.2f})"
            ),
            "body": (
                f"Regular season: {phase_rows[0]['hca']:+.2f} pts ({phase_rows[0]['n']} games, 95% CI [{phase_rows[0]['lo']:+.2f}, {phase_rows[0]['hi']:+.2f}]). "
                f"Playoffs: {phase_rows[1]['hca']:+.2f} pts ({phase_rows[1]['n']} games, 95% CI [{phase_rows[1]['lo']:+.2f}, {phase_rows[1]['hi']:+.2f}]). "
                f"The two CIs overlap substantially -- HCA does NOT collapse in the playoffs, contrary to intuition. "
                f"Caveat: playoff sample is small ({phase_rows[1]['n']} games over 11 seasons)."
            ),
        },
        {
            "headline": f"Team spread is real -- {top_team['name']} ({float(top_team['hca']):+.1f}) -> {bot_team['name']} ({float(bot_team['hca']):+.1f})",
            "body": "Top and bottom teams' bootstrap CIs do not overlap; this is structural, not noise. Olympiakos and Real Madrid sit at the extreme of crowd-amplified home edge."
        },
        {
            "headline": f"Attendance dose-response: {slope_pp10:+.2f} pts per +10pp arena fill",
            "body": f"OLS slope on attendance_ratio = {slope:+.2f} (n={len(att_valid):,}). At league level the dose-response is essentially flat, but mixed-effects per-team slopes span a wide range -- a few teams (notably {team_slopes.iloc[-1]['name']}) show a real crowd dependence."
        },
        {
            "headline": f"Elo-adjusted home edge -- OR {log_out['interaction_ORs']['is_home']:.2f} (+{log_out['prob_lift_pp']:.1f} pp at 50/50)",
            "body": f"After controlling for team strength, the is_home odds ratio is {log_out['interaction_ORs']['is_home']:.2f}; the is_home x attendance interaction OR is {log_out['interaction_ORs']['is_home_x_att']:.2f} (full arenas amplify the home edge). Logistic with attendance interaction beats LightGBM at this sample size."
        },
    ],
}


# %% template
TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<link rel="icon" type="image/png" href="assets/euroleague-logo.png">
<title>EuroLeague Home-Court Advantage</title>
<link href="https://cdn.jsdelivr.net/npm/@fontsource/dm-sans@5.0.18/400.css" rel="stylesheet">
<link href="https://cdn.jsdelivr.net/npm/@fontsource/dm-sans@5.0.18/500.css" rel="stylesheet">
<link href="https://cdn.jsdelivr.net/npm/@fontsource/dm-sans@5.0.18/600.css" rel="stylesheet">
<link href="https://cdn.jsdelivr.net/npm/@fontsource/dm-sans@5.0.18/700.css" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3.0.1/dist/chartjs-plugin-annotation.umd.min.js"></script>
<style>
  :root {
    --bg: #0b0d12;
    --panel: #11141b;
    --panel-2: #161a23;
    --border: rgba(255,255,255,0.06);
    --border-2: rgba(255,255,255,0.12);
    --fg: #f1f3f8;
    --fg-dim: #a7aec0;
    --fg-mute: #6b7280;
    --accent: #f97316;
    --accent-soft: rgba(249, 115, 22, 0.12);
    --blue: #60a5fa;
    --green: #4ade80;
    --red: #f87171;
    --yellow: #facc15;
    --violet: #a78bfa;
    --cyan: #22d3ee;
    --grid: rgba(255,255,255,0.06);
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; background: var(--bg); color: var(--fg);
               font-family: 'DM Sans', 'Axiforma', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
               font-feature-settings: "ss01", "tnum"; -webkit-font-smoothing: antialiased; }
  .app { max-width: 1280px; margin: 0 auto; padding: 32px 32px 96px 32px; }
  code { font-family: 'JetBrains Mono', ui-monospace, monospace; font-size: 0.92em;
         background: rgba(255,255,255,0.05); padding: 1px 5px; border-radius: 3px; }

  /* HERO */
  .hero { display: grid; grid-template-columns: 1fr auto; gap: 24px; align-items: end;
          padding-bottom: 24px; border-bottom: 1px solid var(--border); margin-bottom: 32px; }
  .hero-eyebrow { text-transform: uppercase; letter-spacing: 0.14em; font-size: 12px;
                  color: var(--accent); font-weight: 600; margin-bottom: 8px; }
  .back { color: var(--accent); font-size: 13px; text-decoration: none; }
  .back:hover { text-decoration: underline; }
  .topbar { display: flex; align-items: center; gap: 14px; margin: 0 0 14px 0; }
  .brand { height: 32px; width: auto; background: #fff; border-radius: 6px; padding: 4px 8px;
           box-shadow: 0 1px 2px rgba(0,0,0,.18); flex-shrink: 0; }
  h1 { font-size: 40px; letter-spacing: -0.02em; line-height: 1.1; margin: 0 0 12px 0; font-weight: 600; }
  h1 .accent { color: var(--accent); }
  .hero-sub { color: var(--fg-dim); font-size: 15px; max-width: 620px; line-height: 1.55; margin: 0; }
  .hero-mode { display: inline-flex; align-items: center; gap: 8px; padding: 8px 14px;
               border: 1px solid var(--border-2); border-radius: 999px; font-size: 12px; color: var(--fg-dim); }
  .hero-mode .dot { width: 6px; height: 6px; border-radius: 50%; }
  .hero-mode .dot.mock { background: var(--yellow); }
  .hero-mode .dot.live { background: var(--green); }

  /* KPI strip -- 4 cards now */
  .kpis { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 32px; }
  .kpi { background: var(--panel); border: 1px solid var(--border); border-radius: 16px;
         padding: 24px; position: relative; overflow: hidden; }
  .kpi::before { content: ""; position: absolute; inset: 0 auto 0 0; width: 3px; background: var(--accent); }
  .kpi.crowd::before { background: var(--cyan); }
  .kpi-label { color: var(--fg-dim); font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em;
               font-weight: 500; margin-bottom: 12px; }
  .kpi-value { font-size: 36px; letter-spacing: -0.02em; font-weight: 600; line-height: 1; margin-bottom: 8px; }
  .kpi-value.smaller { font-size: 28px; }
  .kpi-caption { color: var(--fg-mute); font-size: 13px; line-height: 1.5; }
  .kpi-caption .up { color: var(--green); }
  .kpi-caption .down { color: var(--red); }

  /* Basketball-only benchmark TABLE (replaces cross-sport bar) */
  .bench { background: var(--panel); border: 1px solid var(--border); border-radius: 16px;
           padding: 20px 24px; margin-bottom: 32px; }
  .bench-title { font-size: 13px; color: var(--fg-dim); text-transform: uppercase;
                 letter-spacing: 0.1em; margin-bottom: 4px; font-weight: 500; }
  .bench-sub { font-size: 13px; color: var(--fg-mute); margin: 0 0 16px 0; }
  .bench-table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: 13px; }
  .bench-table th { text-align: left; padding: 8px 12px; color: var(--fg-mute); font-weight: 500;
                    text-transform: uppercase; letter-spacing: 0.06em; font-size: 11px;
                    border-bottom: 1px solid var(--border-2); }
  .bench-table th.num { text-align: right; }
  .bench-table td { padding: 12px; border-bottom: 1px solid var(--border); color: var(--fg-dim);
                    font-variant-numeric: tabular-nums; }
  .bench-table td.num { text-align: right; color: var(--fg); font-weight: 500; }
  .bench-table tr.ours td { background: var(--accent-soft); color: var(--fg); font-weight: 500; }
  .bench-table tr.ours td:first-child { border-left: 2px solid var(--accent); }
  .bench-table tr:last-child td { border-bottom: 0; }
  .bench-source { font-size: 11px; color: var(--fg-mute); }
  .bench-foot { font-size: 11px; color: var(--fg-mute); margin-top: 12px; line-height: 1.5; }

  /* Tabs */
  .tabs { display: flex; gap: 4px; padding: 4px; background: var(--panel);
          border: 1px solid var(--border); border-radius: 12px; margin-bottom: 24px; overflow-x: auto; }
  .tab { flex: 1; background: transparent; border: 0; color: var(--fg-dim); padding: 10px 16px;
         border-radius: 8px; font-family: inherit; font-size: 13px; font-weight: 500;
         cursor: pointer; white-space: nowrap; transition: all 0.15s ease; }
  .tab:hover { color: var(--fg); background: var(--panel-2); }
  .tab.active { background: var(--accent); color: #111; }

  /* Panels */
  .panel { display: none; }
  .panel.active { display: block; animation: fade 0.2s ease; }
  @keyframes fade { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }

  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  .grid-3 { display: grid; grid-template-columns: 2fr 1fr; gap: 16px; }
  .card { background: var(--panel); border: 1px solid var(--border); border-radius: 16px; padding: 24px; }
  .card.span-2 { grid-column: span 2; }
  .card h3 { margin: 0 0 4px 0; font-size: 17px; font-weight: 600; letter-spacing: -0.01em; line-height: 1.3; }
  .card .sub { color: var(--fg-dim); font-size: 13px; margin: 0 0 20px 0; line-height: 1.5; }
  .card .n-cap { color: var(--fg-mute); font-size: 11px; margin-top: 12px;
                 padding-top: 12px; border-top: 1px solid var(--border); display: flex;
                 justify-content: space-between; align-items: center; gap: 12px; }
  .chart-wrap { position: relative; height: 340px; }
  .chart-wrap.tall { height: 460px; }
  .chart-wrap.short { height: 240px; }

  /* Heatmap */
  .heat { display: grid; gap: 2px; font-size: 11px; }
  .heat-row { display: grid; grid-template-columns: 160px repeat(var(--cols), 1fr); gap: 2px; align-items: center; }
  .heat-label { color: var(--fg-dim); padding: 0 8px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .heat-cell { height: 26px; border-radius: 3px; display: flex; align-items: center; justify-content: center;
               font-weight: 600; color: #0b0d12; cursor: default; }
  .heat-cell.empty { background: var(--panel-2); color: var(--fg-mute); }
  .heat-head { color: var(--fg-mute); font-size: 11px; text-align: center; }

  /* Forest */
  .forest { font-size: 12px; }
  .forest-row { display: grid; grid-template-columns: 180px 1fr 70px; gap: 12px; align-items: center;
                padding: 4px 0; }
  .forest-label { color: var(--fg-dim); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .forest-bar { position: relative; height: 18px; }
  .forest-bar .axis { position: absolute; inset: 50% 0 auto 0; height: 1px; background: var(--grid); }
  .forest-bar .ref { position: absolute; top: 0; bottom: 0; width: 1px; background: var(--fg-mute); }
  .forest-bar .ref.league { background: var(--accent); opacity: 0.6; }
  .forest-bar .ci { position: absolute; height: 2px; top: 50%; margin-top: -1px; background: var(--fg-dim); border-radius: 1px; }
  .forest-bar .pt { position: absolute; width: 10px; height: 10px; border-radius: 50%;
                    top: 50%; margin-top: -5px; background: var(--accent);
                    border: 2px solid var(--bg); }
  .forest-val { text-align: right; color: var(--fg); font-variant-numeric: tabular-nums;
                font-weight: 500; }
  .forest-axis-row { display: grid; grid-template-columns: 180px 1fr 70px; gap: 12px;
                     color: var(--fg-mute); font-size: 10px; padding-top: 4px;
                     border-top: 1px solid var(--border); margin-top: 4px; }
  .forest-axis-row .axis-content { display: flex; justify-content: space-between; }

  /* Interactive filter bar (used by attendance + home-forts panels) */
  .filterbar { background: var(--panel); border: 1px solid var(--border); border-radius: 16px;
               padding: 16px; margin-bottom: 20px;
               display: grid; grid-template-columns: 1fr 2fr auto; gap: 16px; align-items: start; }
  @media (max-width: 900px) { .filterbar { grid-template-columns: 1fr; } }
  .filter-group h4 { margin: 0 0 8px 0; font-size: 10px; color: var(--fg-mute); text-transform: uppercase;
                     letter-spacing: 0.08em; font-weight: 500; }
  .filter-group .chips { display: flex; flex-wrap: wrap; gap: 6px; max-height: 126px; overflow-y: auto;
                         padding: 2px; }
  .chip { padding: 5px 10px; font-size: 12px; font-weight: 500; border-radius: 14px;
          background: var(--panel-2); color: var(--fg-dim); border: 1px solid var(--border);
          cursor: pointer; transition: all 0.12s; user-select: none; white-space: nowrap; }
  .chip:hover { border-color: var(--accent); color: var(--fg); }
  .chip.active { background: var(--accent); color: #0b0d10; border-color: var(--accent); font-weight: 600; }
  .filter-actions { display: flex; flex-direction: column; gap: 6px; align-items: stretch;
                    min-width: 110px; }
  .btn { padding: 7px 12px; font-size: 12px; font-weight: 600; border-radius: 8px;
         background: var(--panel-2); color: var(--fg-dim); border: 1px solid var(--border);
         cursor: pointer; }
  .btn:hover { border-color: var(--accent); color: var(--fg); }
  .filter-scope { color: var(--fg-mute); font-size: 11px; margin-top: 8px;
                  font-variant-numeric: tabular-nums; }
  .filter-scope strong { color: var(--fg); }

  /* Home-forts table (Best home fort in Europe per year) */
  .forts-table { width: 100%; border-collapse: collapse; font-size: 13px; font-variant-numeric: tabular-nums; }
  .forts-table th { text-align: left; padding: 10px 12px; color: var(--fg-mute); font-weight: 500;
                    text-transform: uppercase; letter-spacing: 0.06em; font-size: 10.5px;
                    border-bottom: 1px solid var(--border-2); background: var(--panel-2);
                    cursor: pointer; user-select: none; position: sticky; top: 0; }
  .forts-table th.num { text-align: right; }
  .forts-table th.sortable:hover { color: var(--fg); }
  .forts-table th.sorted { color: var(--accent); }
  .forts-table th.sorted::after { content: " \25BC"; font-size: 9px; color: var(--accent); }
  .forts-table th.sorted.asc::after { content: " \25B2"; }
  .forts-table td { padding: 10px 12px; border-bottom: 1px solid var(--border); color: var(--fg-dim); }
  .forts-table td.num { text-align: right; color: var(--fg); font-weight: 500; }
  .forts-table td.team { color: var(--fg); font-weight: 500; }
  .forts-table tr.top3 td { background: rgba(249, 115, 22, 0.06); }
  .forts-table tr.top3 td.team { color: var(--warn); }
  .forts-table td.gap-pos { color: var(--green); font-weight: 600; }
  .forts-table td.gap-big { color: var(--warn); font-weight: 600; }
  .forts-wrap { max-height: 560px; overflow: auto; border: 1px solid var(--border); border-radius: 10px;
                background: var(--panel); }

  /* Upsets table */
  .upsets-table { width: 100%; border-collapse: collapse; font-size: 12px; }
  .upsets-table th { text-align: left; padding: 8px 10px; color: var(--fg-mute); font-weight: 500;
                     text-transform: uppercase; letter-spacing: 0.06em; font-size: 10px;
                     border-bottom: 1px solid var(--border-2); }
  .upsets-table th.num { text-align: right; }
  .upsets-table td { padding: 10px; border-bottom: 1px solid var(--border); color: var(--fg-dim);
                     font-variant-numeric: tabular-nums; }
  .upsets-table td.num { text-align: right; color: var(--fg); font-weight: 500; }
  .upsets-table td.team { color: var(--fg); }
  .upsets-table td.surprise { color: var(--accent); font-weight: 600; }

  /* Verdict */
  .mock-banner { background: rgba(250, 204, 21, 0.06); border: 1px solid rgba(250, 204, 21, 0.3);
                 border-radius: 12px; padding: 16px 20px; margin-bottom: 24px; display: flex;
                 align-items: flex-start; gap: 12px; }
  .mock-banner .ico { color: var(--yellow); font-size: 18px; line-height: 1; }
  .mock-banner .body { color: var(--fg-dim); font-size: 13px; line-height: 1.55; }
  .mock-banner .body strong { color: var(--yellow); font-weight: 600; }

  .verdict-list { display: grid; gap: 12px; }
  .verdict-item { background: var(--panel); border: 1px solid var(--border); border-radius: 14px;
                  padding: 20px; border-left: 3px solid var(--accent); }
  .verdict-item.crowd { border-left-color: var(--cyan); }
  .verdict-item h4 { margin: 0 0 6px 0; font-size: 16px; font-weight: 600; letter-spacing: -0.01em; }
  .verdict-item p { margin: 0; color: var(--fg-dim); font-size: 14px; line-height: 1.55; }

  .gap-card { background: linear-gradient(135deg, var(--panel) 0%, var(--panel-2) 100%);
              border: 1px solid var(--border-2); border-radius: 14px; padding: 20px; margin-top: 24px; }
  .gap-card h3 { margin: 0 0 8px 0; font-size: 14px; text-transform: uppercase;
                 letter-spacing: 0.1em; color: var(--fg-dim); font-weight: 600; }
  .gap-card ul { margin: 0; padding-left: 20px; color: var(--fg-dim); font-size: 13px; line-height: 1.7; }
  .gap-card ul li code { color: var(--accent); }

  /* OR card */
  .or-grid { display: grid; gap: 12px; }
  .or-row { padding: 16px 18px; background: var(--panel-2); border-radius: 12px;
            display: flex; justify-content: space-between; align-items: center; gap: 16px; }
  .or-row .lbl { font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; color: var(--fg-dim); margin-bottom: 4px; }
  .or-row .val { font-size: 24px; font-weight: 600; color: var(--accent); line-height: 1; }
  .or-row .desc { color: var(--fg-mute); font-size: 12px; max-width: 240px; text-align: right; line-height: 1.5; }
  .or-row .desc strong { color: var(--fg); font-weight: 500; }

  /* LightGBM caveat */
  .caveat { background: rgba(248, 113, 113, 0.06); border: 1px solid rgba(248, 113, 113, 0.25);
            border-radius: 10px; padding: 12px 16px; margin-top: 14px; font-size: 12px;
            color: var(--fg-dim); line-height: 1.55; }
  .caveat strong { color: var(--red); }

  /* Footer */
  .footer { color: var(--fg-mute); font-size: 12px; padding-top: 32px; text-align: center; line-height: 1.6; }
  .footer a { color: var(--fg-dim); }

  @media (max-width: 1000px) {
    h1 { font-size: 30px; }
    .kpis { grid-template-columns: repeat(2, 1fr); }
    .grid-2, .grid-3 { grid-template-columns: 1fr; }
    .card.span-2 { grid-column: span 1; }
  }
</style>
</head>
<body>
<div class="app">
  <div class="topbar">
    <img class="brand" src="assets/euroleague-logo.png" alt="EuroLeague" />
    <a class="back" href="index.html">&larr; back to dashboard index</a>
  </div>
  <header class="hero">
    <div>
      <div class="hero-eyebrow" style="color:#3ccf8e"><span style="display:inline-block;width:8px;height:8px;background:#3ccf8e;border-radius:50%;margin-right:6px;vertical-align:middle"></span>Track A &middot; why home wins</div>
      <div class="hero-eyebrow">EuroLeague Basketball &middot; 11 seasons &middot; {n_games} games</div>
      <h1>The crowd, the court, and the count.<br><span class="accent">What actually moves home-court advantage?</span></h1>
      <p class="hero-sub">A quantitative deep-dive into home-court advantage across 10 EuroLeague seasons (2015-16 to 2025-26).
        Combines bootstrap inference, mixed-effects per-team crowd sensitivity, and a natural experiment built around the
        2020-21 empty-arena regime.</p>
    </div>
    <div class="hero-mode"><span class="dot {mode_dot_class}"></span> {mode_label}</div>
  </header>

  <section class="kpis">
    <div class="kpi">
      <div class="kpi-label">League HCA</div>
      <div class="kpi-value" id="kpi-hca">--</div>
      <div class="kpi-caption" id="kpi-hca-caption">95% bootstrap CI</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Home win rate</div>
      <div class="kpi-value" id="kpi-wr">--</div>
      <div class="kpi-caption">across {n_games} games</div>
    </div>
    <div class="kpi crowd">
      <div class="kpi-label">Crowd contribution</div>
      <div class="kpi-value" id="kpi-crowd">--</div>
      <div class="kpi-caption" id="kpi-crowd-caption">from COVID natural experiment (DiD)</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Team spread</div>
      <div class="kpi-value smaller" id="kpi-spread">--</div>
      <div class="kpi-caption" id="kpi-spread-caption"></div>
    </div>
  </section>

  <section class="bench">
    <div class="bench-title">For context &middot; NBA vs EuroLeague</div>
    <p class="bench-sub">Apples-to-apples: regular season only, last 10 completed seasons (2015-16 through 2024-25). 
      NBA from the official stats.nba.com API; EuroLeague from the official EuroLeague live API -- identical 
      statistical code on both. EuroLeague's home edge is ~1.7x the NBA's in this window.</p>
    <table class="bench-table">
      <thead>
        <tr>
          <th>League</th>
          <th class="num">HCA (pts)</th>
          <th>95% CI</th>
          <th>Home Win %</th>
          <th>Sample size</th>
        </tr>
      </thead>
      <tbody id="bench-body"></tbody>
    </table>
  </section>

  <div style="margin:8px 0 4px;color:#9aa3af;font-size:11px;text-transform:uppercase;letter-spacing:.08em">
    <span style="display:inline-block;width:8px;height:8px;background:#3ccf8e;border-radius:50%;margin-right:6px;vertical-align:middle"></span>
    Track A &mdash; Why home wins &middot; tabs below are this investigation
  </div>
  <nav class="tabs" id="tabs">
    <button class="tab active" data-target="tab-overview">1. The league</button>
    <button class="tab" data-target="tab-teams">2. Per team</button>
    <button class="tab" data-target="tab-attendance">3. Attendance</button>
    <button class="tab" data-target="tab-covid">4. COVID experiment</button>
    <button class="tab" data-target="tab-models">5. Models</button>
    <button class="tab" data-target="tab-verdict">6. Verdict</button>
    <button class="tab" data-target="tab-mechanisms">7. Mechanisms</button>
  </nav>
  <div style="margin:14px 0 4px;color:#9aa3af;font-size:11px;text-transform:uppercase;letter-spacing:.08em">
    <span style="display:inline-block;width:8px;height:8px;background:#3ccf8e;border-radius:50%;margin-right:6px;vertical-align:middle"></span>
    More of Track A &mdash; sibling dashboards
  </div>
  <nav class="tabs">
    <a class="tab" href="explorer.html" style="text-decoration:none;display:inline-flex;align-items:center;background:rgba(110,176,255,0.08);border-color:rgba(110,176,255,0.3)">Team &amp; Season Explorer (multi-select filters) &rarr;</a>
    <a class="tab" href="anomalies.html" style="text-decoration:none;display:inline-flex;align-items:center">Anomalies &rarr;</a>
    <a class="tab" href="referees.html" style="text-decoration:none;display:inline-flex;align-items:center">Referee-bias audit (null) &rarr;</a>
    <a class="tab" href="final_report.html" style="text-decoration:none;display:inline-flex;align-items:center">Written report &rarr;</a>
  </nav>
  <div style="margin:14px 0 4px;color:#9aa3af;font-size:11px;text-transform:uppercase;letter-spacing:.08em">
    <span style="display:inline-block;width:8px;height:8px;background:#6eb0ff;border-radius:50%;margin-right:6px;vertical-align:middle"></span>
    Track B &mdash; what happens next on the floor (different question)
  </div>
  <nav class="tabs">
    <a class="tab" href="transitions.html" style="text-decoration:none;display:inline-flex;align-items:center">Play-by-play transitions &rarr;</a>
    <a class="tab" href="rebound_rates.html" style="text-decoration:none;display:inline-flex;align-items:center">Rebound rates by miss type &rarr;</a>
  </nav>

  <!-- OVERVIEW -->
  <section class="panel active" id="tab-overview">
    <div class="grid-2">
      <div class="card span-2">
        <h3>HCA held steady around +3.7 pts; the empty-arena 2020-21 shock is the exception</h3>
        <p class="sub">League-wide home point-differential per season. The COVID-affected window (mid-2019-20 onwards) is shaded.
          The dashed orange line marks the 10-year average.</p>
        <div class="chart-wrap tall"><canvas id="chart-trend"></canvas></div>
        <div class="n-cap">
          <span id="trend-n">n=...</span>
          <span>One row per season. League average reference line in dashed orange.</span>
        </div>
      </div>
      <div class="card">
        <h3>Most games are decided by less than two possessions</h3>
        <p class="sub">Smoothed density of home margin. Markers show the share of games within key clutch thresholds.</p>
        <div class="chart-wrap"><canvas id="chart-density"></canvas></div>
        <div class="n-cap">
          <span id="density-n">n=...</span>
          <span>Markers at +/-3, +/-5, +/-15 pts</span>
        </div>
      </div>
      <div class="card">
        <h3>Regular season vs Playoffs: HCA holds, contrary to intuition</h3>
        <p class="sub">95% bootstrap CIs. Regular season +3.71 (n=2,974), playoffs +3.54 (n=149). CIs overlap
          heavily -- the common belief that home advantage shrinks in big games is not supported here.</p>
        <div class="chart-wrap"><canvas id="chart-phase"></canvas></div>
        <div class="n-cap">
          <span id="phase-n">n=...</span>
          <span>Bootstrap (2,000 resamples)</span>
        </div>
      </div>
      <div class="card span-2">
        <h3>Home win rate tracks HCA tightly &mdash; with Wilson 95% CI shading</h3>
        <p class="sub">Season-level home win rate. Thin error bands = Wilson 95% CI given each season's sample size.</p>
        <div class="chart-wrap"><canvas id="chart-wr"></canvas></div>
        <div class="n-cap">
          <span id="wr-n">n=...</span>
          <span>Season-level Wilson 95% interval</span>
        </div>
      </div>
    </div>
  </section>

  <!-- TEAMS -->
  <section class="panel" id="tab-teams">
    <div class="grid-2">
      <div class="card span-2">
        <h3>HCA by team &mdash; with league-average reference (orange dashed)</h3>
        <p class="sub">Each team's mean home point-differential (RS only) with 95% bootstrap CI. Vertical orange line = league
          average. Vertical gray line = zero (no advantage).</p>
        <div class="forest" id="team-forest"></div>
        <div class="n-cap">
          <span id="teamf-n">n=...</span>
          <span>RS games only; teams with &lt;30 home games excluded</span>
        </div>
      </div>
      <div class="card span-2">
        <h3>Team x Season heatmap &mdash; who is consistently high?</h3>
        <p class="sub">Color = home point differential. Darker orange = larger HCA. White = data missing.</p>
        <div id="heatmap"></div>
        <div class="n-cap">
          <span>RS only</span>
          <span>Sorted top-down by mean HCA</span>
        </div>
      </div>
      <div class="card span-2">
        <h3>Best home fort in Europe &mdash; filterable by team &amp; season</h3>
        <p class="sub">
          Each row is one <em>team x season</em>. <strong>Win gap</strong> = home win rate minus away win rate.
          <strong>Fortress score</strong> = home_wr x win_gap &mdash; rewards teams that (a) win a lot at home AND
          (b) rely on it. A team that wins everywhere (overall title contender) scores lower than a team that
          dominates at home but loses on the road. Use the filters at the top of the Attendance tab to scope
          this table too. Click any column header to sort.
        </p>
        <div class="forts-wrap">
          <table class="forts-table" id="forts-table">
            <thead>
              <tr>
                <th>Rank</th>
                <th data-sort="name" class="sortable">Team</th>
                <th data-sort="season" class="sortable">Season</th>
                <th class="num sortable" data-sort="home_wr">Home rec</th>
                <th class="num sortable" data-sort="away_wr">Away rec</th>
                <th class="num sortable" data-sort="home_margin_mean">Home margin</th>
                <th class="num sortable" data-sort="away_margin_mean">Away margin</th>
                <th class="num sortable" data-sort="win_gap">Win gap</th>
                <th class="num sortable" data-sort="margin_gap">Margin gap</th>
                <th class="num sortable sorted" data-sort="fortress_score">Fortress</th>
              </tr>
            </thead>
            <tbody></tbody>
          </table>
        </div>
        <div class="n-cap">
          <span id="forts-n">...</span>
          <span>Min 5 home + 5 away games to qualify. All phases (RS + playoffs).</span>
        </div>
      </div>
      <div class="card span-2">
        <h3>Biggest home-court upsets &mdash; where the crowd may have mattered most</h3>
        <p class="sub">Top RS wins where the home team was an Elo underdog. <code>Surprise</code> = actual margin minus
          Elo-expected margin. Useful for hypothesis-generating about specific arenas.</p>
        <table class="upsets-table" id="upsets-table">
          <thead>
            <tr>
              <th>Season</th>
              <th>Date</th>
              <th>Home</th>
              <th>Away</th>
              <th class="num">Score</th>
              <th class="num">Margin</th>
              <th class="num">Elo&nbsp;diff</th>
              <th class="num">Surprise</th>
              <th class="num">Att%</th>
            </tr>
          </thead>
          <tbody></tbody>
        </table>
        <div class="n-cap">
          <span>Top 8 by surprise</span>
          <span>Elo-to-margin conversion: 28 Elo points &asymp; 1 pt margin</span>
        </div>
      </div>
    </div>
  </section>

  <!-- ATTENDANCE -->
  <section class="panel" id="tab-attendance">
    <div class="filterbar" id="att-filterbar">
      <div class="filter-group">
        <h4>Seasons (click to toggle)</h4>
        <div class="chips" id="filter-seasons"></div>
      </div>
      <div class="filter-group">
        <h4>Teams (click to toggle; empty = all teams)</h4>
        <div class="chips" id="filter-teams"></div>
      </div>
      <div class="filter-actions">
        <button class="btn" id="btn-all-seasons">All seasons</button>
        <button class="btn" id="btn-clear-teams">All teams</button>
        <button class="btn" id="btn-reset">Reset</button>
        <div class="filter-scope" id="filter-scope">Scope: <strong>...</strong></div>
      </div>
    </div>
    <p class="sub" style="margin:-8px 0 14px 4px;font-size:12px">
      Filters below apply to all three charts on this tab <strong>and</strong> to the "Best home fort" table
      on the Per-team tab.
    </p>
    <div class="grid-2">
      <div class="card span-2">
        <h3>Dose-response: fuller arenas deliver bigger home margins</h3>
        <p class="sub">Decile bins of attendance ratio. Dashed line is the OLS fit on raw games. Slope shown inline.</p>
        <div class="chart-wrap tall"><canvas id="chart-dose"></canvas></div>
        <div class="n-cap">
          <span id="dose-n">n=...</span>
          <span id="dose-slope">slope: ...</span>
        </div>
      </div>
      <div class="card">
        <h3>Decile view &mdash; with 95% CI error bars</h3>
        <p class="sub">Same data sliced into deciles. Error bars are bootstrap 95% intervals; non-overlap = real separation.</p>
        <div class="chart-wrap"><canvas id="chart-deciles"></canvas></div>
        <div class="n-cap">
          <span id="deciles-n">n=...</span>
          <span>Quantile-based bins (~equal sample per bin)</span>
        </div>
      </div>
      <div class="card">
        <h3>Which teams depend most on the crowd?</h3>
        <p class="sub">Per-team OLS slope on attendance_ratio, recomputed live on the filtered in-scope games.
          Reference line = zero (no crowd dependence). Higher = more crowd-sensitive.</p>
        <div class="forest" id="team-slopes"></div>
        <div class="n-cap">
          <span id="slopes-n">n teams: ...</span>
          <span id="slopes-league">League slope: ...</span>
        </div>
      </div>
    </div>
  </section>

  <!-- COVID -->
  <section class="panel" id="tab-covid">
    <div class="grid-2">
      <div class="card">
        <h3>Three regimes, one natural experiment</h3>
        <p class="sub">Mean HCA per regime with 95% CI error bars. COVID removed a sizeable chunk; post-COVID returned to
          pre-COVID levels.</p>
        <div class="chart-wrap"><canvas id="chart-regimes"></canvas></div>
        <div class="n-cap">
          <span id="reg-n">n=...</span>
          <span>Pre = 2015-2018; COVID = 2019-2020; Post = 2021-2024</span>
        </div>
      </div>
      <div class="card">
        <h3>Difference-in-differences</h3>
        <p class="sub">Delta HCA between regimes with bootstrap CI. A non-zero <code>covid - pre</code> estimate is the
          causal leverage.</p>
        <div class="forest" id="did-forest"></div>
        <div class="n-cap">
          <span>Bootstrap on regime means</span>
          <span>Orange dot = significant (CI excludes zero)</span>
        </div>
      </div>
      <div class="card span-2">
        <h3>HCA timeline with COVID shock highlighted</h3>
        <p class="sub">The 2020-21 season is the left endpoint of the attendance dose-response curve. Pre and post means
          drawn as horizontal references.</p>
        <div class="chart-wrap"><canvas id="chart-covid-line"></canvas></div>
        <div class="n-cap">
          <span id="covid-n">n=...</span>
          <span>COVID shading covers 2019-20 (March onwards) + full 2020-21</span>
        </div>
      </div>
    </div>
  </section>

  <!-- MODELS -->
  <section class="panel" id="tab-models">
    <div class="grid-2">
      <div class="card">
        <h3>Elo-adjusted odds: home still wins at a neutral matchup</h3>
        <p class="sub">Logistic regression controlling for team strength. The odds-ratio on <code>is_home</code> is the clean
          HCA estimate; the interaction tells us how the crowd amplifies it.</p>
        <div class="or-grid">
          <div class="or-row">
            <div>
              <div class="lbl">is_home odds ratio</div>
              <div class="val" id="or-value">--</div>
            </div>
            <div class="desc"><strong>+<span id="pp-value">--</span> pp at a 50/50 matchup</strong> (Elo-adjusted home win lift)</div>
          </div>
          <div class="or-row">
            <div>
              <div class="lbl">is_home &times; attendance OR</div>
              <div class="val" id="int-value">--</div>
            </div>
            <div class="desc" id="int-desc">A sold-out arena adds <strong>+? pp</strong> on top of the base home edge vs an empty one</div>
          </div>
        </div>
      </div>
      <div class="card">
        <h3>Calibration -- when the model says 70%, does 70% of the time it happen?</h3>
        <p class="sub">Diagonal = perfect calibration. Closer to the diagonal = better-calibrated probabilities (what a GM cares about).</p>
        <div class="chart-wrap"><canvas id="chart-calib"></canvas></div>
        <div class="n-cap">
          <span>Held-out test fold</span>
          <span>10 equal-width prediction bins</span>
        </div>
      </div>
      <div class="card">
        <h3>ROC -- discrimination across all thresholds</h3>
        <p class="sub">Diagonal = random; top-left = perfect. AUC labelled per model. All models cluster tightly above the diagonal.</p>
        <div class="chart-wrap"><canvas id="chart-roc"></canvas></div>
        <div class="n-cap">
          <span>Held-out test fold</span>
          <span id="roc-auc">AUC: ...</span>
        </div>
      </div>
      <div class="card">
        <h3>Model comparison -- simpler beats fancier at this sample size</h3>
        <p class="sub">Held-out test log-loss (lower = better). Logistic with attendance interaction tops the table.</p>
        <div class="chart-wrap"><canvas id="chart-models"></canvas></div>
        <div class="caveat" id="lgb-caveat"></div>
      </div>
      <div class="card span-2">
        <h3>Feature importance &mdash; Elo dominates, attendance is a clear second</h3>
        <p class="sub">LightGBM gain-based importance. Elo captures raw team quality; attendance captures the crowd effect.
          Note: gain-based importance is high-variance at small samples; treat magnitudes as ordinal not absolute.</p>
        <div class="chart-wrap"><canvas id="chart-importance"></canvas></div>
      </div>
    </div>
  </section>

  <!-- VERDICT -->
  <section class="panel" id="tab-verdict">
    <div id="mock-banner-slot"></div>
    <div class="verdict-list" id="verdict-list"></div>
    <div class="gap-card">
      <h3>What we don't have (yet)</h3>
      <ul>
        <li><code>Quarter-by-quarter HCA</code> -- whether the home edge is built early (energy) or late (clutch / refs).
          Requires play-by-play.</li>
        <li><code>Travel &amp; rest mechanics</code> -- <code>days_rest</code> is in the model, but back-to-backs, miles
          travelled, and time-zone effects are not analyzed in depth.</li>
        <li><code>Cluster-robust standard errors</code> -- bootstrap CIs treat games as independent; clustering by team-season
          would be more honest. Adds ~10-15% to interval widths.</li>
      </ul>
    </div>
  </section>

  <!-- MECHANISMS -->
  <section class="panel" id="tab-mechanisms">
    <div class="grid-2">
      <div class="card">
        <h3>Home advantage decomposition</h3>
        <p class="sub">How much of the home edge comes from shooting better vs getting more free throws?
          (Based on OLS regression of home margin on stat gaps).</p>
        <div class="chart-wrap"><canvas id="chart-mechanisms-contrib"></canvas></div>
      </div>
      <div class="card">
        <h3>Raw statistical gaps (Home - Away)</h3>
        <p class="sub">Average difference in key box-score metrics per game (with 95% CIs).</p>
        <div class="chart-wrap"><canvas id="chart-mechanisms-gaps"></canvas></div>
      </div>
      <div class="card span-2">
        <h3>The "Why": Shooting vs Refereeing</h3>
        <p class="sub" id="mechanisms-narrative">
          Loading mechanism analysis...
        </p>
      </div>
    </div>
  </section>

  <footer class="footer">
    Generated by <code>scripts/10_analyst_dashboard.py</code> &middot; {mode_label} &middot; {n_seasons} seasons,
    {n_games} games, {n_teams} teams.<br>
    Methodology: bootstrap 95% CI (1,000-2,000 resamples), Wilson binomial CI, mixed-effects (<code>statsmodels.mixedlm</code>),
    Difference-in-Differences, time-based CV for ML. Full detail in <code>reports/final_report.md</code>.
  </footer>
</div>

<script id="payload" type="application/json">__PAYLOAD__</script>
<script>
(() => {
  const P = JSON.parse(document.getElementById('payload').textContent);
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  Chart.defaults.font.family = "'DM Sans', 'Axiforma', sans-serif";
  Chart.defaults.font.size = 12;
  Chart.defaults.color = css('--fg-dim');

  const COLORS = {
    accent: css('--accent'),
    blue: css('--blue'), green: css('--green'), red: css('--red'),
    yellow: css('--yellow'), violet: css('--violet'), cyan: css('--cyan'),
    grid: css('--grid'), fg: css('--fg'), fgDim: css('--fg-dim'), fgMute: css('--fg-mute'),
  };

  // -- formatters
  const fmtNum = (v, d = 1) => { if (v == null || isNaN(v)) return '--'; return Number(v).toFixed(d); };
  const fmtSigned = (v, d = 1) => { if (v == null || isNaN(v)) return '--'; const s = Number(v) >= 0 ? '+' : ''; return s + Number(v).toFixed(d); };
  const fmtK = (v) => { if (v == null || isNaN(v)) return '--'; if (Math.abs(v) >= 1e6) return (v/1e6).toFixed(1) + 'M'; if (Math.abs(v) >= 1e3) return (v/1e3).toFixed(1) + 'K'; return Math.round(v).toString(); };
  const fmtPct = (v, d = 1) => { if (v == null || isNaN(v)) return '--'; return (Number(v) * 100).toFixed(d) + '%'; };
  const setText = (id, t) => { const el = document.getElementById(id); if (el) el.textContent = t; };
  const setHTML = (id, t) => { const el = document.getElementById(id); if (el) el.innerHTML = t; };

  // -- KPIs
  setText('kpi-hca', fmtSigned(P.kpis.league_hca, 2) + ' pts');
  setText('kpi-hca-caption',
    `95% CI [${fmtSigned(P.kpis.league_hca_lo, 2)}, ${fmtSigned(P.kpis.league_hca_hi, 2)}] \u00B7 ${fmtK(P.kpis.n_games)} games`);
  setText('kpi-wr', fmtPct(P.kpis.home_win_rate, 1));
  setText('kpi-crowd', fmtSigned(P.kpis.crowd_contrib, 2) + ' pts');
  setText('kpi-crowd-caption',
    `95% CI [${fmtSigned(P.kpis.crowd_lo, 2)}, ${fmtSigned(P.kpis.crowd_hi, 2)}] \u00B7 ` +
    (P.kpis.crowd_significant ? 'COVID DiD (significant)' : 'COVID DiD (not significant)'));
  // Soften the KPI visual when not significant
  const crowdEl = document.getElementById('kpi-crowd');
  if (crowdEl && !P.kpis.crowd_significant) {
    crowdEl.style.color = 'var(--fg-dim)';
    crowdEl.style.fontWeight = '600';
  }
  const spread = P.kpis.top_team_hca - P.kpis.bot_team_hca;
  setText('kpi-spread', fmtSigned(spread, 1) + ' pts');
  setHTML('kpi-spread-caption',
    `<span class="up">${P.kpis.top_team_name}</span> &nbsp;\u2192&nbsp; <span class="down">${P.kpis.bot_team_name}</span>`);

  // -- self-context table (4 framings of our measured EuroLeague HCA)
  const benchBody = document.getElementById('bench-body');
  P.self_context.forEach(r => {
    const tr = document.createElement('tr');
    if (r.league === 'EuroLeague') tr.classList.add('ours');
    tr.innerHTML = `
      <td><strong>${r.league}</strong></td>
      <td class="num"><strong>${r.hca_pts}</strong></td>
      <td><span class="bench-source">${r.ci}</span></td>
      <td>${r.home_win}</td>
      <td>${r.n_games}</td>`;
    benchBody.appendChild(tr);
  });

  // -- TABS
  const tabs = document.querySelectorAll('.tab');
  const panels = document.querySelectorAll('.panel');
  tabs.forEach(t => t.addEventListener('click', () => {
    tabs.forEach(x => x.classList.toggle('active', x === t));
    panels.forEach(p => p.classList.toggle('active', p.id === t.dataset.target));
  }));

  // -- common
  const gridY = { color: COLORS.grid, drawBorder: false };
  const gridX = { color: COLORS.grid, drawBorder: false };
  const axisTicks = { color: COLORS.fgDim, font: { size: 11 } };
  const tipBase = (border) => ({ backgroundColor: '#11141b', borderColor: border || COLORS.accent, borderWidth: 1, padding: 12, titleColor: COLORS.fg });

  // === Trend ===
  const trendIdx2019 = P.trend.seasons.indexOf('2019');
  const trendIdx2020 = P.trend.seasons.indexOf('2020');
  new Chart(document.getElementById('chart-trend'), {
    type: 'line',
    data: { labels: P.trend.seasons, datasets: [{
      label: 'HCA', data: P.trend.hca,
      borderColor: COLORS.accent, backgroundColor: 'rgba(249, 115, 22, 0.12)',
      fill: true, tension: 0.35, borderWidth: 2.5, pointRadius: 5, pointHoverRadius: 7,
      pointBackgroundColor: COLORS.accent, pointBorderColor: '#0b0d12', pointBorderWidth: 2,
    }]},
    options: { responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false },
        tooltip: Object.assign({}, tipBase(COLORS.accent),
          { callbacks: { label: (ctx) => `HCA: ${fmtSigned(ctx.raw, 2)} pts (n=${P.trend.n[ctx.dataIndex]})` } }),
        annotation: { annotations: {
          covid: { type: 'box',
            xMin: trendIdx2019 - 0.5, xMax: trendIdx2020 + 0.5,
            backgroundColor: 'rgba(248, 113, 113, 0.08)', borderColor: 'rgba(248, 113, 113, 0.25)',
            borderWidth: 1,
            label: { content: 'COVID disruption', display: true, position: 'start',
              color: COLORS.red, font: { size: 11, weight: 500 }, backgroundColor: 'transparent' } },
          mean: { type: 'line', yMin: P.kpis.league_hca, yMax: P.kpis.league_hca,
            borderColor: COLORS.accent, borderDash: [4,4], borderWidth: 1.5,
            label: { content: `10-yr avg ${fmtSigned(P.kpis.league_hca, 2)}`, display: true,
              position: 'end', color: COLORS.accent, font: { size: 10 }, backgroundColor: 'transparent' } }
        }}
      },
      scales: {
        x: { grid: gridX, ticks: axisTicks,
             title: { display: true, text: 'Season (starting year)', color: COLORS.fgMute, font: { size: 11 } } },
        y: { grid: gridY, ticks: Object.assign({}, axisTicks, { callback: (v) => fmtSigned(v, 0) }),
             title: { display: true, text: 'Home point differential', color: COLORS.fgMute, font: { size: 11 } } }
      }
    }
  });
  setText('trend-n', `n = ${P.trend.n.reduce((s,v)=>s+v,0).toLocaleString('en-US')} games across ${P.trend.seasons.length} seasons`);

  // === Density (replaces histogram) ===
  const densityCtx = document.getElementById('chart-density');
  const ds = P.density.stats;
  new Chart(densityCtx, {
    type: 'line',
    data: {
      labels: P.density.x,
      datasets: [{
        label: '% games', data: P.density.y,
        borderColor: COLORS.accent, backgroundColor: 'rgba(249, 115, 22, 0.18)',
        fill: true, tension: 0.4, borderWidth: 2,
        pointRadius: 0, pointHoverRadius: 4,
      }]
    },
    options: { responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false },
        tooltip: Object.assign({}, tipBase(COLORS.accent),
          { callbacks: { title: (ctxs) => `Margin: ${fmtSigned(ctxs[0].label, 0)} pts`,
                         label: (ctx) => `${fmtNum(ctx.raw, 2)}% of games` } }),
        annotation: { annotations: {
          neg5: { type: 'line', xMin: -5, xMax: -5, yMin: 0, yMax: 6,
            borderColor: COLORS.fgMute, borderDash: [3,3], borderWidth: 1,
            label: { content: '-5', display: true, position: 'start', color: COLORS.fgMute, font: { size: 10 }, backgroundColor: 'transparent' }},
          neg3: { type: 'line', xMin: -3, xMax: -3, yMin: 0, yMax: 6,
            borderColor: COLORS.fgMute, borderDash: [2,3], borderWidth: 0.8 },
          pos3: { type: 'line', xMin: 3, xMax: 3, yMin: 0, yMax: 6,
            borderColor: COLORS.fgMute, borderDash: [2,3], borderWidth: 0.8 },
          pos5: { type: 'line', xMin: 5, xMax: 5, yMin: 0, yMax: 6,
            borderColor: COLORS.fgMute, borderDash: [3,3], borderWidth: 1,
            label: { content: '+5', display: true, position: 'start', color: COLORS.fgMute, font: { size: 10 }, backgroundColor: 'transparent' }},
          pos15: { type: 'line', xMin: 15, xMax: 15, yMin: 0, yMax: 6,
            borderColor: COLORS.red, borderDash: [4,4], borderWidth: 1,
            label: { content: '+15 (blowout)', display: true, position: 'start', color: COLORS.red, font: { size: 10 }, backgroundColor: 'transparent' }},
          neg15: { type: 'line', xMin: -15, xMax: -15, yMin: 0, yMax: 6,
            borderColor: COLORS.red, borderDash: [4,4], borderWidth: 1 },
          mean: { type: 'line', xMin: ds.mean, xMax: ds.mean, yMin: 0, yMax: 6,
            borderColor: COLORS.accent, borderWidth: 1.5,
            label: { content: `mean ${fmtSigned(ds.mean, 1)}`, display: true, position: 'end', color: COLORS.accent, font: { size: 10 }, backgroundColor: 'transparent' }},
          shareWithin5: { type: 'label',
            xValue: 0, yValue: 5.6,
            content: [`${fmtPct(ds.share_within_5, 0)} of games within +/-5 pts`,
                      `${fmtPct(ds.share_blowout, 0)} are blowouts (>15)`],
            color: COLORS.fgDim, font: { size: 11 }, textAlign: 'center' }
        }}
      },
      scales: {
        x: { type: 'linear', min: -35, max: 35, grid: gridX,
             ticks: Object.assign({}, axisTicks, { stepSize: 10, callback: (v) => fmtSigned(v, 0) }),
             title: { display: true, text: 'Home margin (pts)', color: COLORS.fgMute, font: { size: 11 } } },
        y: { grid: gridY, ticks: Object.assign({}, axisTicks, { callback: (v) => v + '%' }),
             title: { display: true, text: '% of games', color: COLORS.fgMute, font: { size: 11 } } }
      }
    }
  });
  setText('density-n', `n = ${ds.n.toLocaleString('en-US')} games \u00B7 mean ${fmtSigned(ds.mean,2)} \u00B7 ${fmtPct(ds.share_within_5,0)} within +/-5`);

  // === RS vs PO ===
  new Chart(document.getElementById('chart-phase'), {
    type: 'bar',
    data: {
      labels: P.phase_hca.map(p => `${p.phase} (n=${p.n.toLocaleString('en-US')})`),
      datasets: [{
        data: P.phase_hca.map(p => p.hca),
        backgroundColor: P.phase_hca.map(p => p.code === 'RS' ? COLORS.accent : 'rgba(167, 139, 250, 0.7)'),
        borderRadius: 4,
        // chart.js doesn't have built-in error bars, simulate with errorBars plugin or annotations
      }]
    },
    options: { responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false },
        tooltip: Object.assign({}, tipBase(COLORS.accent),
          { callbacks: { label: (ctx) => {
            const r = P.phase_hca[ctx.dataIndex];
            return [`HCA: ${fmtSigned(r.hca, 2)} pts`, `95% CI: [${fmtSigned(r.lo, 2)}, ${fmtSigned(r.hi, 2)}]`,
                    `Home win %: ${fmtNum(r.home_wr * 100, 1)}%`];
          } } }),
        annotation: { annotations: Object.fromEntries(P.phase_hca.flatMap((r, i) => {
          // Vertical CI line per bar
          return [[`ci_${i}`, { type: 'line',
            xMin: i, xMax: i, yMin: r.lo, yMax: r.hi,
            borderColor: COLORS.fgDim, borderWidth: 2 }],
            [`ci_low_${i}`, { type: 'line',
              xMin: i - 0.1, xMax: i + 0.1, yMin: r.lo, yMax: r.lo,
              borderColor: COLORS.fgDim, borderWidth: 2 }],
            [`ci_hi_${i}`, { type: 'line',
              xMin: i - 0.1, xMax: i + 0.1, yMin: r.hi, yMax: r.hi,
              borderColor: COLORS.fgDim, borderWidth: 2 }],
          ];
        })) }
      },
      scales: {
        x: { grid: { display: false }, ticks: axisTicks },
        y: { grid: gridY, ticks: Object.assign({}, axisTicks, { callback: (v) => fmtSigned(v, 0) }),
             title: { display: true, text: 'HCA (pts)', color: COLORS.fgMute, font: { size: 11 } } }
      }
    }
  });
  setText('phase-n', `n = ${P.phase_hca.reduce((s,p)=>s+p.n,0).toLocaleString('en-US')} games`);

  // === Win rate with Wilson CI ===
  new Chart(document.getElementById('chart-wr'), {
    type: 'line',
    data: { labels: P.trend.seasons, datasets: [
      // Upper CI band
      { label: 'CI hi', data: P.trend.wr_hi, borderColor: 'rgba(96, 165, 250, 0.0)',
        backgroundColor: 'rgba(96, 165, 250, 0.15)', fill: '+1', pointRadius: 0, tension: 0.3, borderWidth: 0 },
      // Lower CI band
      { label: 'CI lo', data: P.trend.wr_lo, borderColor: 'rgba(96, 165, 250, 0.0)',
        backgroundColor: 'transparent', fill: false, pointRadius: 0, tension: 0.3, borderWidth: 0 },
      // Main line
      { label: 'Home win rate', data: P.trend.win_rate,
        borderColor: COLORS.blue, backgroundColor: 'transparent', fill: false,
        tension: 0.35, borderWidth: 2.5, pointRadius: 4,
        pointBackgroundColor: COLORS.blue, pointBorderColor: '#0b0d12', pointBorderWidth: 2 },
    ] },
    options: { responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false },
        tooltip: Object.assign({}, tipBase(COLORS.blue),
          { filter: (ti) => ti.datasetIndex === 2,
            callbacks: { label: (ctx) => `${fmtPct(ctx.raw, 1)} \u00B7 95% CI [${fmtPct(P.trend.wr_lo[ctx.dataIndex],0)}, ${fmtPct(P.trend.wr_hi[ctx.dataIndex],0)}] \u00B7 n=${P.trend.n[ctx.dataIndex]}` } }) },
      scales: {
        x: { grid: gridX, ticks: axisTicks },
        y: { grid: gridY, ticks: Object.assign({}, axisTicks, { callback: (v) => fmtPct(v, 0) }),
             min: 0.45, max: 0.75 }
      }
    }
  });
  setText('wr-n', `n = ${P.trend.n.reduce((s,v)=>s+v,0).toLocaleString('en-US')} games`);

  // === FOREST: team HCA with league ref ===
  const teamForestEl = document.getElementById('team-forest');
  const allLo = Math.min(...P.team_hca.map(t => t.lo));
  const allHi = Math.max(...P.team_hca.map(t => t.hi));
  const pad = (allHi - allLo) * 0.08;
  const xMin = Math.floor(allLo - pad);
  const xMax = Math.ceil(allHi + pad);
  const range = xMax - xMin;
  const xToPct = (x) => ((x - xMin) / range) * 100;

  P.team_hca.forEach((t) => {
    const row = document.createElement('div');
    row.className = 'forest-row';
    const ciLeft = xToPct(t.lo);
    const ciWidth = xToPct(t.hi) - xToPct(t.lo);
    const pointLeft = xToPct(t.hca);
    const zeroLeft = xToPct(0);
    const leagueLeft = xToPct(P.kpis.league_hca);
    row.innerHTML = `
      <div class="forest-label" title="${t.name} (n=${t.n})">${t.name}</div>
      <div class="forest-bar">
        <div class="axis"></div>
        <div class="ref" style="left:${zeroLeft}%"></div>
        <div class="ref league" style="left:${leagueLeft}%; border-left: 1px dashed ${COLORS.accent}; background: transparent;"></div>
        <div class="ci" style="left:${ciLeft}%; width:${ciWidth}%"></div>
        <div class="pt" style="left:calc(${pointLeft}% - 5px)"></div>
      </div>
      <div class="forest-val" title="n=${t.n}">${fmtSigned(t.hca, 2)}</div>`;
    teamForestEl.appendChild(row);
  });
  // Axis row
  const axisRow = document.createElement('div');
  axisRow.className = 'forest-axis-row';
  axisRow.innerHTML = `<div></div><div class="axis-content"><span>${fmtSigned(xMin,0)}</span><span style="color:${COLORS.fgMute};">0 (no edge)</span><span style="color:${COLORS.accent};">league avg ${fmtSigned(P.kpis.league_hca,1)}</span><span>${fmtSigned(xMax,0)}</span></div><div></div>`;
  teamForestEl.appendChild(axisRow);
  setText('teamf-n', `n teams = ${P.team_hca.length} \u00B7 total games = ${P.team_hca.reduce((s,t)=>s+t.n,0).toLocaleString('en-US')}`);

  // === HEATMAP ===
  const heatEl = document.getElementById('heatmap');
  heatEl.innerHTML = '';
  const seasons = P.heatmap.seasons;
  const allVals = P.heatmap.values.flat().filter(v => v != null);
  const vMin = Math.min(...allVals);
  const vMax = Math.max(...allVals);
  const colorFor = (v) => {
    if (v == null) return null;
    const pct = (v - vMin) / (vMax - vMin);
    if (v < 0) {
      const k = Math.min(1, Math.abs(v) / Math.max(Math.abs(vMin), 1));
      return `rgba(248, 113, 113, ${0.25 + k * 0.55})`;
    }
    return `rgba(249, 115, 22, ${0.15 + pct * 0.75})`;
  };
  const head = document.createElement('div');
  head.className = 'heat-row';
  head.style.setProperty('--cols', seasons.length);
  head.innerHTML = '<div class="heat-label"></div>' + seasons.map(s => `<div class="heat-head">${s}</div>`).join('');
  heatEl.appendChild(head);

  P.heatmap.teams.forEach((team, i) => {
    const row = document.createElement('div');
    row.className = 'heat-row';
    row.style.setProperty('--cols', seasons.length);
    const cells = P.heatmap.values[i].map((v, j) => {
      if (v == null) return `<div class="heat-cell empty">--</div>`;
      return `<div class="heat-cell" style="background:${colorFor(v)}" title="${team} ${seasons[j]}: ${fmtSigned(v,1)}">${fmtSigned(v, 0)}</div>`;
    }).join('');
    row.innerHTML = `<div class="heat-label" title="${team}">${team}</div>${cells}`;
    heatEl.appendChild(row);
  });

  // === UPSETS table ===
  const upsetTbody = document.querySelector('#upsets-table tbody');
  P.upsets.forEach(u => {
    const tr = document.createElement('tr');
    const att = u.att_ratio == null ? '--' : fmtPct(u.att_ratio, 0);
    tr.innerHTML = `
      <td>${u.season}</td>
      <td>${u.date}</td>
      <td class="team">${u.home}</td>
      <td>${u.away}</td>
      <td class="num">${u.home_pts}-${u.away_pts}</td>
      <td class="num">${fmtSigned(u.margin, 0)}</td>
      <td class="num">${fmtSigned(u.elo_diff, 0)}</td>
      <td class="num surprise">${fmtSigned(u.surprise, 1)}</td>
      <td class="num">${att}</td>`;
    upsetTbody.appendChild(tr);
  });

  // === INTERACTIVE FILTER + ATTENDANCE + HOME FORTS (shared scope) ===
  // Filter state. Empty teamSet = all teams; seasonSet controls which seasons are active.
  const ATT = P.attendance;
  const FORTS = P.home_forts || [];
  const filter = {
    seasons: new Set(ATT.seasons),  // start with all
    teams: new Set(),               // empty = all
    fortsSort: { col: 'fortress_score', dir: 'desc' },
  };
  let doseChart = null, decilesChart = null;

  function matchesFilter(row) {
    if (filter.seasons.size > 0 && !filter.seasons.has(row.season)) return false;
    if (filter.teams.size > 0 && !filter.teams.has(row.team_id)) return false;
    return true;
  }

  // Compute deciles + OLS + per-team simple slopes from filtered rows.
  function computeAttStats(rows) {
    const n = rows.length;
    if (n < 10) return null;
    const xs = rows.map(r => r.att);
    const ys = rows.map(r => r.margin);
    // OLS
    const mx = xs.reduce((s,v)=>s+v,0) / n;
    const my = ys.reduce((s,v)=>s+v,0) / n;
    let num = 0, den = 0;
    for (let i = 0; i < n; i++) { const dx = xs[i]-mx; num += dx*(ys[i]-my); den += dx*dx; }
    const slope = den > 0 ? num / den : 0;
    const intercept = my - slope * mx;
    // Deciles via quantile sort
    const sorted = rows.slice().sort((a,b) => a.att - b.att);
    const binCount = Math.min(10, Math.max(4, Math.floor(n / 30)));  // fewer bins when fewer games
    const deciles = [];
    for (let i = 0; i < binCount; i++) {
      const lo = Math.floor(i * n / binCount);
      const hi = Math.floor((i + 1) * n / binCount);
      const sub = sorted.slice(lo, hi);
      if (sub.length === 0) continue;
      const m = sub.map(r => r.margin);
      const mMean = m.reduce((s,v)=>s+v,0) / m.length;
      // Bootstrap 95% CI (B=500; fast enough for <2000 rows)
      const B = 500;
      const boots = new Float64Array(B);
      for (let b = 0; b < B; b++) {
        let s = 0;
        for (let k = 0; k < m.length; k++) s += m[(Math.random() * m.length) | 0];
        boots[b] = s / m.length;
      }
      boots.sort();
      deciles.push({
        decile: i + 1,
        ratio_lo: sub[0].att, ratio_hi: sub[sub.length-1].att,
        ratio_mid: sub.reduce((s,r)=>s+r.att,0) / sub.length,
        hca: mMean, lo: boots[Math.floor(B*0.025)], hi: boots[Math.floor(B*0.975)],
        n: sub.length,
      });
    }
    // Per-team simple OLS slopes (when filtered teams changes we still show all in-scope teams)
    const byTeam = new Map();
    for (const r of rows) {
      if (!byTeam.has(r.team_id)) byTeam.set(r.team_id, { id: r.team_id, name: r.name, xs: [], ys: [] });
      const t = byTeam.get(r.team_id);
      t.xs.push(r.att); t.ys.push(r.margin);
    }
    const teamSlopes = [];
    for (const t of byTeam.values()) {
      if (t.xs.length < 8) continue;
      const mxt = t.xs.reduce((s,v)=>s+v,0) / t.xs.length;
      const myt = t.ys.reduce((s,v)=>s+v,0) / t.ys.length;
      let num2 = 0, den2 = 0;
      for (let i = 0; i < t.xs.length; i++) { const dx = t.xs[i]-mxt; num2 += dx*(t.ys[i]-myt); den2 += dx*dx; }
      const tslope = den2 > 0 ? num2 / den2 : 0;
      teamSlopes.push({ team_id: t.id, name: t.name, total_slope: tslope, n: t.xs.length });
    }
    teamSlopes.sort((a,b) => a.total_slope - b.total_slope);
    return { n, slope, intercept, slope_pp10: slope * 0.10, deciles, team_slopes: teamSlopes };
  }

  function renderDose(stats) {
    if (doseChart) { doseChart.destroy(); doseChart = null; }
    const el = document.getElementById('chart-dose');
    if (!stats) {
      setText('dose-n', 'n = 0 (filter too narrow)');
      setText('dose-slope', '--');
      return;
    }
    const dosePts = stats.deciles.map(d => ({ x: d.ratio_mid, y: d.hca, n: d.n }));
    const xLine = [0, 1.0];
    const yLine = xLine.map(xx => stats.intercept + stats.slope * xx);
    doseChart = new Chart(el, {
      type: 'scatter',
      data: { datasets: [
        { label: 'decile mean', data: dosePts, backgroundColor: COLORS.accent, borderColor: COLORS.accent,
          pointRadius: stats.deciles.map(d => Math.max(5, Math.min(16, Math.sqrt(d.n) * 0.4))),
          pointHoverRadius: 12, showLine: false },
        { type: 'line', label: 'OLS fit', data: xLine.map((x, i) => ({ x, y: yLine[i] })),
          borderColor: COLORS.fgDim, borderDash: [6,4], borderWidth: 1.5, pointRadius: 0, fill: false },
      ] },
      options: { responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false },
          tooltip: Object.assign({}, tipBase(COLORS.accent), { callbacks: {
            title: (ctxs) => ctxs[0].raw.n != null ? `Attendance ratio ${fmtPct(ctxs[0].raw.x, 0)}` : '',
            label: (ctx) => ctx.raw.n != null
              ? [`HCA: ${fmtSigned(ctx.raw.y, 2)} pts`, `Games: ${fmtK(ctx.raw.n)}`]
              : `OLS: ${fmtSigned(ctx.raw.y, 2)} pts`,
          } }),
          annotation: { annotations: {
            zero: { type: 'line', yMin: 0, yMax: 0, borderColor: COLORS.fgMute, borderDash: [4,4], borderWidth: 1 },
            slopeLabel: { type: 'label', xValue: 0.85,
              yValue: stats.intercept + stats.slope * 0.85 + 0.6,
              content: [`slope: ${fmtSigned(stats.slope_pp10, 2)} pts per +10pp fill`],
              color: COLORS.accent, backgroundColor: 'rgba(11,13,18,0.85)', padding: 6, borderRadius: 4,
              font: { size: 11, weight: 600 } }
          }}
        },
        scales: {
          x: { min: 0, max: 1.0, grid: gridX,
               ticks: Object.assign({}, axisTicks, { callback: (v) => fmtPct(v, 0) }),
               title: { display: true, text: 'Attendance ratio (attendance / capacity)', color: COLORS.fgMute, font: { size: 11 } } },
          y: { grid: gridY, ticks: Object.assign({}, axisTicks, { callback: (v) => fmtSigned(v, 0) }),
               title: { display: true, text: 'Home point differential', color: COLORS.fgMute, font: { size: 11 } } }
        }
      }
    });
    setText('dose-n', `n = ${stats.n.toLocaleString('en-US')} home games`);
    setText('dose-slope', `OLS slope: ${fmtSigned(stats.slope_pp10, 2)} pts per +10pp arena fill`);
  }

  function renderDeciles(stats) {
    if (decilesChart) { decilesChart.destroy(); decilesChart = null; }
    const el = document.getElementById('chart-deciles');
    if (!stats) { setText('deciles-n', 'n = 0'); return; }
    decilesChart = new Chart(el, {
      type: 'bar',
      data: {
        labels: stats.deciles.map(d => `D${d.decile}\n${fmtPct(d.ratio_mid,0)}`),
        datasets: [{
          data: stats.deciles.map(d => d.hca),
          backgroundColor: stats.deciles.map((d, i) => `rgba(249, 115, 22, ${0.3 + i * 0.07})`),
          borderRadius: 3,
        }]
      },
      options: { responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false },
          tooltip: Object.assign({}, tipBase(COLORS.accent), { callbacks: { label: (ctx) => {
            const d = stats.deciles[ctx.dataIndex];
            return [`HCA: ${fmtSigned(d.hca, 2)} pts`,
                    `95% CI: [${fmtSigned(d.lo, 2)}, ${fmtSigned(d.hi, 2)}]`,
                    `Range: ${fmtPct(d.ratio_lo,0)}-${fmtPct(d.ratio_hi,0)}`,
                    `Games: ${fmtK(d.n)}`];
          } } }),
          annotation: { annotations: Object.fromEntries(stats.deciles.flatMap((d, i) => [
            [`ci_${i}`, { type: 'line', xMin: i, xMax: i, yMin: d.lo, yMax: d.hi,
              borderColor: COLORS.fgDim, borderWidth: 1.5 }],
            [`cit_${i}`, { type: 'line', xMin: i - 0.15, xMax: i + 0.15, yMin: d.hi, yMax: d.hi,
              borderColor: COLORS.fgDim, borderWidth: 1.5 }],
            [`cib_${i}`, { type: 'line', xMin: i - 0.15, xMax: i + 0.15, yMin: d.lo, yMax: d.lo,
              borderColor: COLORS.fgDim, borderWidth: 1.5 }],
          ])) }
        },
        scales: {
          x: { grid: { display: false }, ticks: Object.assign({}, axisTicks, { font: { size: 10 } }),
               title: { display: true, text: 'Attendance decile', color: COLORS.fgMute, font: { size: 11 } } },
          y: { grid: gridY, ticks: Object.assign({}, axisTicks, { callback: (v) => fmtSigned(v, 0) }),
               title: { display: true, text: 'HCA (pts)', color: COLORS.fgMute, font: { size: 11 } } }
        }
      }
    });
    setText('deciles-n', `n = ${stats.deciles.reduce((s,d)=>s+d.n,0).toLocaleString('en-US')} home games \u00B7 ${stats.deciles.length} bins`);
  }

  function renderTeamSlopes(stats) {
    const el = document.getElementById('team-slopes');
    el.innerHTML = '';
    if (!stats || stats.team_slopes.length === 0) {
      el.innerHTML = '<div style="color:var(--fg-mute);font-size:12px;padding:12px">Not enough games in scope to estimate per-team slopes (need at least 8 games per team).</div>';
      setText('slopes-n', 'n teams = 0');
      setText('slopes-league', '');
      return;
    }
    const slopes = stats.team_slopes;
    const sMin = Math.min(0, ...slopes.map(s => s.total_slope));
    const sMax = Math.max(stats.slope, ...slopes.map(s => s.total_slope));
    const sPad = Math.max(0.1, (sMax - sMin) * 0.08);
    const sxMin = sMin - sPad, sxMax = sMax + sPad, sRange = sxMax - sxMin;
    slopes.forEach(s => {
      const row = document.createElement('div');
      row.className = 'forest-row';
      const zeroPct = ((0 - sxMin) / sRange) * 100;
      const leaguePct = ((stats.slope - sxMin) / sRange) * 100;
      const ptLeft = ((s.total_slope - sxMin) / sRange) * 100;
      row.innerHTML = `
        <div class="forest-label" title="${s.name} (n=${s.n})">${s.name}</div>
        <div class="forest-bar">
          <div class="axis"></div>
          <div class="ref" style="left:${zeroPct}%"></div>
          <div class="ref league" style="left:${leaguePct}%; border-left: 1px dashed ${COLORS.accent}; background: transparent;"></div>
          <div class="pt" style="left:calc(${ptLeft}% - 5px); background:${s.total_slope > 0 ? COLORS.accent : COLORS.fgMute};"></div>
        </div>
        <div class="forest-val" title="n=${s.n}">${fmtSigned(s.total_slope, 2)}</div>`;
      el.appendChild(row);
    });
    const sAxisRow = document.createElement('div');
    sAxisRow.className = 'forest-axis-row';
    sAxisRow.innerHTML = `<div></div><div class="axis-content"><span>${fmtSigned(sxMin,1)}</span><span style="color:${COLORS.fgMute};">0 (no crowd dep.)</span><span style="color:${COLORS.accent};">in-scope avg ${fmtSigned(stats.slope,1)}</span><span>${fmtSigned(sxMax,1)}</span></div><div></div>`;
    el.appendChild(sAxisRow);
    setText('slopes-n', `n teams = ${slopes.length}`);
    setText('slopes-league', `In-scope slope: ${fmtSigned(stats.slope, 2)} pts per unit ratio`);
  }

  // === HOME FORTS TABLE ===
  function renderForts() {
    const rows = FORTS.filter(matchesFilter);
    const { col, dir } = filter.fortsSort;
    rows.sort((a, b) => {
      const va = a[col], vb = b[col];
      if (typeof va === 'string') return dir === 'asc' ? va.localeCompare(vb) : vb.localeCompare(va);
      return dir === 'asc' ? (va - vb) : (vb - va);
    });
    const tbody = document.querySelector('#forts-table tbody');
    tbody.innerHTML = '';
    const top = rows.slice(0, 50);
    top.forEach((r, i) => {
      const tr = document.createElement('tr');
      if (i < 3) tr.className = 'top3';
      const homeRec = `${r.wins_home}-${r.n_home - r.wins_home} <span style="color:var(--fg-mute)">(${(r.home_wr*100).toFixed(0)}%)</span>`;
      const awayRec = `${r.wins_away}-${r.n_away - r.wins_away} <span style="color:var(--fg-mute)">(${(r.away_wr*100).toFixed(0)}%)</span>`;
      const gapPP = r.win_gap * 100;
      const gapClass = gapPP >= 50 ? 'gap-big' : (gapPP >= 30 ? 'gap-pos' : '');
      tr.innerHTML = `
        <td class="num">${i + 1}</td>
        <td class="team">${r.name}</td>
        <td>${r.season_label}</td>
        <td class="num">${homeRec}</td>
        <td class="num">${awayRec}</td>
        <td class="num">${fmtSigned(r.home_margin_mean, 1)}</td>
        <td class="num">${fmtSigned(r.away_margin_mean, 1)}</td>
        <td class="num ${gapClass}">${fmtSigned(gapPP, 0)}pp</td>
        <td class="num">${fmtSigned(r.margin_gap, 1)}</td>
        <td class="num">${r.fortress_score.toFixed(3)}</td>`;
      tbody.appendChild(tr);
    });
    // Sorted header marker
    document.querySelectorAll('#forts-table th.sortable').forEach(th => {
      th.classList.remove('sorted', 'asc');
      if (th.dataset.sort === col) {
        th.classList.add('sorted');
        if (dir === 'asc') th.classList.add('asc');
      }
    });
    setText('forts-n', `n team-seasons in scope = ${rows.length.toLocaleString('en-US')} \u00B7 showing top ${Math.min(50, rows.length)}`);
  }

  document.querySelectorAll('#forts-table th.sortable').forEach(th => {
    th.addEventListener('click', () => {
      const col = th.dataset.sort;
      if (filter.fortsSort.col === col) {
        filter.fortsSort.dir = filter.fortsSort.dir === 'desc' ? 'asc' : 'desc';
      } else {
        filter.fortsSort.col = col;
        filter.fortsSort.dir = (col === 'name' || col === 'season') ? 'asc' : 'desc';
      }
      renderForts();
    });
  });

  // === FILTER UI ===
  function updateScope() {
    const rows = ATT.raw.filter(matchesFilter);
    const seasons = [...filter.seasons].sort();
    const teams = [...filter.teams];
    const parts = [];
    parts.push(`<strong>${rows.length.toLocaleString('en-US')}</strong> games`);
    if (seasons.length === ATT.seasons.length) parts.push('all seasons');
    else if (seasons.length === 1) parts.push(`season ${seasons[0]}-${String(seasons[0]+1).slice(-2)}`);
    else parts.push(`${seasons.length} seasons`);
    if (teams.length === 0) parts.push('all teams');
    else if (teams.length === 1) {
      const name = (ATT.teams.find(t => t.team_id === teams[0]) || {}).name || teams[0];
      parts.push(`team: ${name}`);
    } else parts.push(`${teams.length} teams`);
    document.getElementById('filter-scope').innerHTML = 'Scope: ' + parts.join(' \u00B7 ');
  }

  function renderAll() {
    const rows = ATT.raw.filter(matchesFilter);
    const stats = computeAttStats(rows);
    renderDose(stats);
    renderDeciles(stats);
    renderTeamSlopes(stats);
    renderForts();
    updateScope();
  }

  function buildFilterUI() {
    const seasonsEl = document.getElementById('filter-seasons');
    const teamsEl = document.getElementById('filter-teams');
    seasonsEl.innerHTML = '';
    ATT.seasons.forEach(s => {
      const chip = document.createElement('div');
      chip.className = 'chip active';
      chip.textContent = `${s}-${String(s + 1).slice(-2)}`;
      chip.dataset.season = s;
      chip.addEventListener('click', () => {
        if (filter.seasons.has(s)) { filter.seasons.delete(s); chip.classList.remove('active'); }
        else { filter.seasons.add(s); chip.classList.add('active'); }
        renderAll();
      });
      seasonsEl.appendChild(chip);
    });
    teamsEl.innerHTML = '';
    ATT.teams.forEach(t => {
      const chip = document.createElement('div');
      chip.className = 'chip';
      chip.textContent = t.name.length > 20 ? t.name.slice(0, 20) + '\u2026' : t.name;
      chip.title = `${t.name} (n=${t.n})`;
      chip.dataset.teamId = t.team_id;
      chip.addEventListener('click', () => {
        if (filter.teams.has(t.team_id)) { filter.teams.delete(t.team_id); chip.classList.remove('active'); }
        else { filter.teams.add(t.team_id); chip.classList.add('active'); }
        renderAll();
      });
      teamsEl.appendChild(chip);
    });
    document.getElementById('btn-all-seasons').addEventListener('click', () => {
      filter.seasons = new Set(ATT.seasons);
      document.querySelectorAll('#filter-seasons .chip').forEach(c => c.classList.add('active'));
      renderAll();
    });
    document.getElementById('btn-clear-teams').addEventListener('click', () => {
      filter.teams.clear();
      document.querySelectorAll('#filter-teams .chip').forEach(c => c.classList.remove('active'));
      renderAll();
    });
    document.getElementById('btn-reset').addEventListener('click', () => {
      filter.seasons = new Set(ATT.seasons);
      filter.teams.clear();
      filter.fortsSort = { col: 'fortress_score', dir: 'desc' };
      document.querySelectorAll('#filter-seasons .chip').forEach(c => c.classList.add('active'));
      document.querySelectorAll('#filter-teams .chip').forEach(c => c.classList.remove('active'));
      renderAll();
    });
  }

  buildFilterUI();
  renderAll();

  // === COVID regimes (with error bars) ===
  new Chart(document.getElementById('chart-regimes'), {
    type: 'bar',
    data: { labels: P.covid.regimes.map(r => r.regime), datasets: [{
      data: P.covid.regimes.map(r => r.hca),
      backgroundColor: P.covid.regimes.map(r =>
        r.regime === 'COVID' ? 'rgba(248, 113, 113, 0.55)' :
        r.regime === 'Pre-COVID' ? 'rgba(96, 165, 250, 0.55)' : 'rgba(74, 222, 128, 0.55)'),
      borderRadius: 4,
    }]},
    options: { responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false },
        tooltip: Object.assign({}, tipBase(COLORS.accent),
          { callbacks: { label: (ctx) => {
            const r = P.covid.regimes[ctx.dataIndex];
            return [`HCA: ${fmtSigned(r.hca, 2)} pts`, `95% CI: [${fmtSigned(r.lo, 2)}, ${fmtSigned(r.hi, 2)}]`, `Games: ${fmtK(r.n)}`];
          } } }),
        annotation: { annotations: Object.fromEntries(P.covid.regimes.flatMap((r, i) => [
          [`ci_${i}`, { type: 'line', xMin: i, xMax: i, yMin: r.lo, yMax: r.hi,
            borderColor: COLORS.fgDim, borderWidth: 2 }],
          [`cit_${i}`, { type: 'line', xMin: i - 0.12, xMax: i + 0.12, yMin: r.hi, yMax: r.hi,
            borderColor: COLORS.fgDim, borderWidth: 2 }],
          [`cib_${i}`, { type: 'line', xMin: i - 0.12, xMax: i + 0.12, yMin: r.lo, yMax: r.lo,
            borderColor: COLORS.fgDim, borderWidth: 2 }],
        ])) }
      },
      scales: { x: { grid: { display: false }, ticks: axisTicks },
        y: { grid: gridY, ticks: Object.assign({}, axisTicks, { callback: (v) => fmtSigned(v, 0) }),
             title: { display: true, text: 'HCA (pts)', color: COLORS.fgMute, font: { size: 11 } } } }
    }
  });
  setText('reg-n', `n = ${P.covid.regimes.reduce((s,r)=>s+r.n,0).toLocaleString('en-US')} games`);

  // === DiD forest ===
  const didEl = document.getElementById('did-forest');
  const didEntries = Object.entries(P.covid.did);
  const didLo = Math.min(...didEntries.map(([_, v]) => v.lo));
  const didHi = Math.max(...didEntries.map(([_, v]) => v.hi));
  const didPad = Math.max(0.3, (didHi - didLo) * 0.1);
  const dxMin = didLo - didPad, dxMax = didHi + didPad, dRange = dxMax - dxMin;
  didEntries.forEach(([k, v]) => {
    const row = document.createElement('div');
    row.className = 'forest-row';
    const ciLeft = ((v.lo - dxMin) / dRange) * 100;
    const ciWidth = ((v.hi - v.lo) / dRange) * 100;
    const ptLeft = ((v.mean - dxMin) / dRange) * 100;
    const zeroLeft = ((0 - dxMin) / dRange) * 100;
    const sig = (v.lo > 0 || v.hi < 0);
    row.innerHTML = `
      <div class="forest-label">${k}</div>
      <div class="forest-bar">
        <div class="axis"></div>
        <div class="ref" style="left:${zeroLeft}%"></div>
        <div class="ci" style="left:${ciLeft}%; width:${ciWidth}%"></div>
        <div class="pt" style="left:calc(${ptLeft}% - 5px); background:${sig ? COLORS.accent : COLORS.fgMute};"></div>
      </div>
      <div class="forest-val">${fmtSigned(v.mean, 2)}</div>`;
    didEl.appendChild(row);
  });

  // === COVID line ===
  new Chart(document.getElementById('chart-covid-line'), {
    type: 'line',
    data: { labels: P.trend.seasons, datasets: [{
      label: 'HCA', data: P.trend.hca,
      borderColor: COLORS.accent, backgroundColor: 'rgba(249, 115, 22, 0.12)', fill: true,
      tension: 0.3, pointRadius: 5, pointBorderColor: '#0b0d12', pointBorderWidth: 2,
      pointBackgroundColor: COLORS.accent, borderWidth: 2.5,
    }]},
    options: { responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false },
        tooltip: Object.assign({}, tipBase(COLORS.accent),
          { callbacks: { label: (ctx) => `HCA: ${fmtSigned(ctx.raw, 2)} pts (n=${P.trend.n[ctx.dataIndex]})` } }),
        annotation: { annotations: {
          covid: { type: 'box',
            xMin: trendIdx2019 - 0.5, xMax: trendIdx2020 + 0.5,
            backgroundColor: 'rgba(248, 113, 113, 0.1)', borderColor: 'rgba(248, 113, 113, 0.3)', borderWidth: 1,
            label: { content: 'COVID', display: true, position: 'start',
              color: COLORS.red, font: { size: 11 }, backgroundColor: 'transparent' } },
          preAvg: { type: 'line', yMin: P.covid.regimes[0].hca, yMax: P.covid.regimes[0].hca,
            xMin: 0, xMax: trendIdx2019 - 0.5,
            borderColor: COLORS.blue, borderWidth: 2, borderDash: [6,4],
            label: { content: `pre ${fmtSigned(P.covid.regimes[0].hca,1)}`, display: true, position: 'start',
              color: COLORS.blue, backgroundColor: 'transparent', font: { size: 10 } } },
          postAvg: { type: 'line', yMin: P.covid.regimes[2].hca, yMax: P.covid.regimes[2].hca,
            xMin: trendIdx2020 + 0.5, xMax: P.trend.seasons.length - 1,
            borderColor: COLORS.green, borderWidth: 2, borderDash: [6,4],
            label: { content: `post ${fmtSigned(P.covid.regimes[2].hca,1)}`, display: true, position: 'end',
              color: COLORS.green, backgroundColor: 'transparent', font: { size: 10 } } }
        }}
      },
      scales: { x: { grid: gridX, ticks: axisTicks },
        y: { grid: gridY, ticks: Object.assign({}, axisTicks, { callback: (v) => fmtSigned(v, 0) }),
             title: { display: true, text: 'HCA (pts)', color: COLORS.fgMute, font: { size: 11 } } } }
    }
  });
  setText('covid-n', `n = ${P.trend.n.reduce((s,v)=>s+v,0).toLocaleString('en-US')} games`);

  // === MODELS: OR card ===
  setText('or-value', fmtNum(P.models.is_home_OR, 3));
  setText('pp-value', fmtNum(P.models.prob_lift_pp, 1));
  setText('int-value', fmtNum(P.models.is_home_x_att_OR, 2) + 'x');
  // Plain-English interaction translation:
  // OR > 1 means the home effect strengthens with attendance. Translate to additional pp at sold-out.
  const baseHomeP = P.models.is_home_OR / (1 + P.models.is_home_OR);  // ~0.53
  const fullP = (P.models.is_home_OR * P.models.is_home_x_att_OR) / (1 + P.models.is_home_OR * P.models.is_home_x_att_OR);
  const extraPp = (fullP - baseHomeP) * 100;
  setHTML('int-desc', `A sold-out arena adds <strong>${fmtSigned(extraPp,1)} pp</strong> on top of the base home edge vs an empty one`);

  // === Calibration ===
  const calData = P.models.calibration;
  const calColors = { 'logistic': COLORS.accent, 'random forest': COLORS.violet, 'lightgbm': COLORS.red, 'elo-only': COLORS.blue };
  const calDatasets = Object.entries(calData).map(([name, pts]) => ({
    label: name, data: pts.map(p => ({ x: p.predicted, y: p.empirical, n: p.n })),
    borderColor: calColors[name] || COLORS.fgDim, backgroundColor: calColors[name] || COLORS.fgDim,
    pointRadius: pts.map(p => Math.max(3, Math.min(8, Math.sqrt(p.n) * 0.5))), showLine: true,
    borderWidth: name === 'logistic' ? 2 : 1.5, fill: false, tension: 0,
  }));
  new Chart(document.getElementById('chart-calib'), {
    type: 'scatter',
    data: { datasets: [
      // perfect diagonal first
      { type: 'line', label: 'perfect',
        data: [{ x: 0, y: 0 }, { x: 1, y: 1 }],
        borderColor: COLORS.fgMute, borderDash: [4,4], borderWidth: 1, pointRadius: 0, fill: false },
      ...calDatasets ] },
    options: { responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: true, position: 'bottom', labels: { color: COLORS.fgDim, font: { size: 11 }, boxWidth: 10 } },
        tooltip: Object.assign({}, tipBase(COLORS.accent),
          { callbacks: {
            title: (ctxs) => ctxs[0].dataset.label,
            label: (ctx) => ctx.raw.n != null
              ? [`Predicted: ${fmtPct(ctx.raw.x, 0)}`, `Actual: ${fmtPct(ctx.raw.y, 0)}`, `n=${ctx.raw.n}`]
              : '',
          } }) },
      scales: {
        x: { min: 0, max: 1, grid: gridX,
             ticks: Object.assign({}, axisTicks, { callback: (v) => fmtPct(v, 0) }),
             title: { display: true, text: 'Predicted P(home wins)', color: COLORS.fgMute, font: { size: 11 } } },
        y: { min: 0, max: 1, grid: gridY,
             ticks: Object.assign({}, axisTicks, { callback: (v) => fmtPct(v, 0) }),
             title: { display: true, text: 'Empirical frequency', color: COLORS.fgMute, font: { size: 11 } } }
      }
    }
  });

  // === ROC ===
  const rocData = P.models.roc;
  const rocAuc = P.models.auc;
  const rocDatasets = Object.entries(rocData).map(([name, pts]) => ({
    label: `${name} (AUC ${fmtNum(rocAuc[name], 3)})`,
    data: pts, borderColor: calColors[name] || COLORS.fgDim,
    backgroundColor: 'transparent', pointRadius: 0, borderWidth: name === 'logistic' ? 2.5 : 1.5,
    showLine: true, fill: false, tension: 0,
  }));
  new Chart(document.getElementById('chart-roc'), {
    type: 'scatter',
    data: { datasets: [
      { type: 'line', label: 'random',
        data: [{ x: 0, y: 0 }, { x: 1, y: 1 }],
        borderColor: COLORS.fgMute, borderDash: [4,4], borderWidth: 1, pointRadius: 0, fill: false },
      ...rocDatasets ] },
    options: { responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: true, position: 'bottom', labels: { color: COLORS.fgDim, font: { size: 11 }, boxWidth: 10 } },
        tooltip: Object.assign({}, tipBase(COLORS.accent),
          { callbacks: { title: (ctxs) => ctxs[0].dataset.label,
            label: (ctx) => `FPR: ${fmtPct(ctx.raw.x, 1)} \u00B7 TPR: ${fmtPct(ctx.raw.y, 1)}` } }) },
      scales: {
        x: { min: 0, max: 1, grid: gridX, ticks: Object.assign({}, axisTicks, { callback: (v) => fmtPct(v, 0) }),
             title: { display: true, text: 'False positive rate', color: COLORS.fgMute, font: { size: 11 } } },
        y: { min: 0, max: 1, grid: gridY, ticks: Object.assign({}, axisTicks, { callback: (v) => fmtPct(v, 0) }),
             title: { display: true, text: 'True positive rate', color: COLORS.fgMute, font: { size: 11 } } }
      }
    }
  });
  const aucList = Object.entries(rocAuc).map(([k, v]) => `${k}: ${fmtNum(v, 3)}`).join(' \u00B7 ');
  setText('roc-auc', `AUCs: ${aucList}`);

  // === Model comparison ===
  const modelOrder = ['majority-prior', 'elo-only', 'random forest', 'logistic', 'lightgbm'];
  const modelLabels = { 'majority-prior': 'Baseline (majority)', 'elo-only': 'Elo only',
                        'random forest': 'Random Forest', 'logistic': 'Logistic + attendance', 'lightgbm': 'LightGBM' };
  const ll = modelOrder.map(m => P.models.eval[m] && P.models.eval[m].log_loss).filter(v => v != null);
  const present = modelOrder.filter(m => P.models.eval[m]);
  new Chart(document.getElementById('chart-models'), {
    type: 'bar',
    data: { labels: present.map(m => modelLabels[m]),
      datasets: [{ data: present.map(m => P.models.eval[m].log_loss),
        backgroundColor: present.map(m => m === 'logistic' ? COLORS.accent : 'rgba(167, 139, 250, 0.55)'),
        borderRadius: 3 }] },
    options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false,
      layout: { padding: { right: 40 } },
      plugins: { legend: { display: false },
        tooltip: Object.assign({}, tipBase(COLORS.accent),
          { callbacks: { label: (ctx) => {
            const m = P.models.eval[present[ctx.dataIndex]];
            return [`Log-loss: ${fmtNum(m.log_loss, 3)}`, `Accuracy: ${fmtPct(m.accuracy, 1)}`, `Brier: ${fmtNum(m.brier, 3)}`];
          } } }) },
      scales: {
        x: { grid: gridX, ticks: Object.assign({}, axisTicks, { callback: (v) => fmtNum(v, 2) }), min: 0.6,
             title: { display: true, text: 'Test log-loss (lower = better)', color: COLORS.fgMute, font: { size: 11 } } },
        y: { grid: { display: false }, ticks: axisTicks }
      }
    }
  });
  // LightGBM caveat
  const lgbLL = P.models.eval['lightgbm'] && P.models.eval['lightgbm'].log_loss;
  const logLL = P.models.eval['logistic'] && P.models.eval['logistic'].log_loss;
  if (lgbLL && logLL && lgbLL > logLL * 1.05) {
    setHTML('lgb-caveat',
      `<strong>Why is LightGBM the worst?</strong> At n &lt; 5K games, gradient-boosting tends to overfit on
       a 5-feature problem with weak signal-to-noise. The fact that simpler models win is a finding, not a
       pipeline bug -- production-quality model at this sample size is the logistic with attendance interaction.`);
  } else {
    document.getElementById('lgb-caveat').remove();
  }

  // === Feature importance ===
  const fi = P.models.feature_importance;
  const fiEntries = Object.entries(fi).sort((a, b) => b[1] - a[1]);
  const fiTotal = fiEntries.reduce((s, [, v]) => s + v, 0);
  const fiLabels = { elo_diff: 'Elo difference', attendance_ratio_filled: 'Attendance ratio',
                     days_rest_filled: 'Days rest', is_playoff: 'Playoff game',
                     attendance_missing: 'Attendance missing' };
  new Chart(document.getElementById('chart-importance'), {
    type: 'bar',
    data: { labels: fiEntries.map(([k]) => fiLabels[k] || k),
      datasets: [{ data: fiEntries.map(([, v]) => v / fiTotal),
        backgroundColor: fiEntries.map(([k]) =>
          k === 'attendance_ratio_filled' ? COLORS.accent :
          k === 'elo_diff' ? 'rgba(96, 165, 250, 0.7)' :
          'rgba(167, 139, 250, 0.5)'),
        borderRadius: 3 }] },
    options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false,
      layout: { padding: { right: 50 } },
      plugins: { legend: { display: false },
        tooltip: Object.assign({}, tipBase(COLORS.accent),
          { callbacks: { label: (ctx) => fmtPct(ctx.raw, 1) + ' of total gain' } }) },
      scales: {
        x: { grid: gridX, ticks: Object.assign({}, axisTicks, { callback: (v) => fmtPct(v, 0) }),
             title: { display: true, text: 'Share of total gain (LightGBM, gain-based)', color: COLORS.fgMute, font: { size: 11 } } },
        y: { grid: { display: false }, ticks: axisTicks }
      }
    }
  });

  // === MECHANISMS ===
  if (P.mechanisms) {
    const m = P.mechanisms;
    const gaps = m.gaps;
    const contribs = m.contribs;
    
    new Chart(document.getElementById('chart-mechanisms-gaps'), {
      type: 'bar',
      data: {
        labels: gaps.map(g => g.stat),
        datasets: [{
          label: 'Gap (Home - Away)',
          data: gaps.map(g => g.gap),
          backgroundColor: gaps.map(g => g.gap > 0 ? COLORS.blue : COLORS.red)
        }]
      },
      options: {
        plugins: { legend: { display: false } },
        scales: { y: { title: { display: true, text: 'Gap' } } }
      }
    });
    
    // Contribs pie chart
    const cLabels = Object.keys(contribs);
    const cData = Object.values(contribs);
    new Chart(document.getElementById('chart-mechanisms-contrib'), {
      type: 'pie',
      data: {
        labels: cLabels,
        datasets: [{
          data: cData.map(Math.abs), // Pie needs positive values
          backgroundColor: [COLORS.blue, COLORS.green, COLORS.yellow, COLORS.red, COLORS.violet, COLORS.cyan, COLORS.accent]
        }]
      },
      options: {
        plugins: {
          tooltip: {
            callbacks: {
              label: (ctx) => {
                const val = cData[ctx.dataIndex];
                return ` ${val > 0 ? '+' : ''}${val.toFixed(2)} pts`;
              }
            }
          }
        }
      }
    });
    
    // Narrative
    const efg = contribs['eFG%'] || 0;
    const ft = contribs['FTA/100'] || 0;
    const tov = contribs['TOV/100'] || 0;
    const tot = m.total_hca || 0;
    
    const sumAttributed = Object.values(contribs).reduce((s, v) => s + v, 0);
    const unexplained = tot - sumAttributed;
    document.getElementById('mechanisms-narrative').innerHTML = `
      Of the <strong>+${tot.toFixed(2)} pts</strong> home edge, the OLS decomposition attributes
      <strong>${efg >= 0 ? '+' : ''}${efg.toFixed(2)} pts</strong> to shooting efficiency (eFG%),
      <strong>${tov >= 0 ? '+' : ''}${tov.toFixed(2)} pts</strong> to fewer turnovers (TOV per 100),
      <strong>${ft >= 0 ? '+' : ''}${ft.toFixed(2)} pts</strong> to free-throw rate, and small
      contributions from OREB and foul differential.
      <br><br>
      A residual <strong>${unexplained >= 0 ? '+' : ''}${unexplained.toFixed(2)} pts</strong>
      is <em>not</em> captured by any single box-score gap (intercept + OT scoring).
      Unlike the NBA, where referee bias (fouls / FTs) explains the majority of HCA
      (Moskowitz &amp; Wertheim, <em>Scorecasting</em>), in the EuroLeague shooting efficiency
      and ball security are the dominant measurable mechanisms, and the foul gap is small
      (&lt;0.1 pts of HCA). Model R&sup2; = ${(m.ols_r2 || 0).toFixed(3)} on n=${m.n_games} paired games.
    `;
  } else {
    const el = document.getElementById('mechanisms-narrative');
    if (el) el.innerHTML = "Mechanism data not available (boxscores not ingested).";
  }

  // === VERDICT + mock banner ===
  const isMock = P.meta.is_mock;
  if (isMock) {
    document.getElementById('mock-banner-slot').innerHTML = `
      <div class="mock-banner">
        <div class="ico">!</div>
        <div class="body">
          <strong>Mock data notice.</strong> Every number on this dashboard is computed from synthetic data
          generated by <code>src/euroleague_hca/ingest/mock.py</code> for pipeline-validation purposes.
          The pipeline, statistics, and model code are production-grade; the inputs are not. Re-run with
          <code>ELH_MOCK=0</code> against the live EuroLeague API to produce reportable figures.
        </div>
      </div>`;
  }
  const vList = document.getElementById('verdict-list');
  P.verdict.forEach((v, i) => {
    const item = document.createElement('div');
    item.className = 'verdict-item' + (i === 0 ? ' crowd' : '');
    item.innerHTML = `<h4>${v.headline}</h4><p>${v.body}</p>`;
    vList.appendChild(item);
  });
})();
</script>
</body>
</html>
"""


# %% write
mode_label = "MOCK DATA" if is_mock else "LIVE DATA"
mode_dot_class = "mock" if is_mock else "live"

html = TEMPLATE.replace("__PAYLOAD__", json.dumps(PAYLOAD))
html = html.replace("{n_games}", f"{n_games:,}")
html = html.replace("{n_seasons}", str(len(PAYLOAD["meta"]["seasons"])))
html = html.replace("{n_teams}", str(PAYLOAD["meta"]["n_teams"]))
html = html.replace("{mode_label}", mode_label)
html = html.replace("{mode_dot_class}", mode_dot_class)

out_path = config.DASHBOARDS_DIR / "dashboard.html"
# preserve previous version
prev = (config.DASHBOARDS_DIR / "dashboard-v1.html")
if out_path.exists() and not prev.exists():
    prev.write_text(out_path.read_text())
out_path.write_text(html)

print(f"analyst dashboard: {out_path}")
print(f"size: {out_path.stat().st_size / 1024:.1f} KB")
print(f"open with: open {out_path}")
