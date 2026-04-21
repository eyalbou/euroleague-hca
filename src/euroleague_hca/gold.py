"""Silver -> gold: feature views for HCA analysis.

Tables produced:
- feat_game_team        per (game, team) with is_home, point_diff, pre-game Elos, attendance_*
- feat_team_season_hca  per (team, season): HCA pts, pair-adjusted HCA, n_home, n_away, avg_att_ratio
- feat_pairwise_same_opponent  per (season, team_a, team_b) same-opponent diff
- feat_team_attendance_slope   per team: slope of HCA vs attendance_ratio, bootstrap CI

Attendance buckets:
- closed_doors: ratio == 0
- low:        0 < ratio <= 0.5
- medium:     0.5 < ratio <= 0.8
- high:       0.8 < ratio < 0.98
- sold_out:   ratio >= 0.98
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from euroleague_hca.config import GOLD_DIR, SILVER_DIR
from euroleague_hca.models.elo import walk_forward

log = logging.getLogger("gold")


def _bucket(r: float | None) -> str:
    if r is None or (isinstance(r, float) and np.isnan(r)):
        return "unknown"
    if r <= 0.0:
        return "closed_doors"
    if r <= 0.5:
        return "low"
    if r <= 0.8:
        return "medium"
    if r < 0.98:
        return "high"
    return "sold_out"


def _bootstrap_ci(x: np.ndarray, n: int = 1000, ci: float = 0.95, rng=None) -> tuple[float, float]:
    if rng is None:
        rng = np.random.default_rng(0)
    if len(x) == 0:
        return float("nan"), float("nan")
    draws = rng.choice(x, size=(n, len(x)), replace=True).mean(axis=1)
    lo = np.percentile(draws, (1 - ci) / 2 * 100)
    hi = np.percentile(draws, (1 + ci) / 2 * 100)
    return float(lo), float(hi)


def build_gold() -> dict[str, int]:
    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    fact_game = pd.read_parquet(SILVER_DIR / "fact_game.parquet")
    dim_venue = pd.read_parquet(SILVER_DIR / "dim_venue_season.parquet")

    # ---- Elo walk-forward on fact_game ----
    fact_game = walk_forward(fact_game)

    # ---- feat_game_team ----
    home = fact_game.rename(columns={"home_team_id": "team_id", "away_team_id": "opp_team_id",
                                     "home_elo_pre": "team_elo_pre", "away_elo_pre": "opp_elo_pre"}).copy()
    home["is_home"] = 1
    home["point_diff"] = home["home_pts"] - home["away_pts"]
    home["team_pts"] = home["home_pts"]
    home["opp_pts"] = home["away_pts"]

    away = fact_game.rename(columns={"away_team_id": "team_id", "home_team_id": "opp_team_id",
                                     "away_elo_pre": "team_elo_pre", "home_elo_pre": "opp_elo_pre"}).copy()
    away["is_home"] = 0
    away["point_diff"] = away["away_pts"] - away["home_pts"]
    away["team_pts"] = away["away_pts"]
    away["opp_pts"] = away["home_pts"]

    cols = ["game_id", "season", "phase", "phase_code", "round", "date", "team_id", "opp_team_id",
            "venue_code", "is_home", "point_diff", "team_pts", "opp_pts", "attendance",
            "attendance_source", "is_neutral", "data_source",
            "team_elo_pre", "opp_elo_pre"]
    feat_gt = pd.concat([home[cols], away[cols]], ignore_index=True)

    # Join capacity from dim_venue_season. Prefer per-season match; fall back to any
    # available capacity for the venue (dim_venue_season often has season=0 when the
    # API only exposes one capacity value per venue).
    cap_ss = (
        dim_venue[["venue_code", "season", "capacity"]]
        .drop_duplicates(["venue_code", "season"])
    )
    feat_gt = feat_gt.merge(cap_ss, on=["venue_code", "season"], how="left")
    cap_any = (
        dim_venue[dim_venue["capacity"].notna() & (dim_venue["capacity"] > 0)]
        .sort_values("season", ascending=False)
        .drop_duplicates(subset=["venue_code"], keep="first")
        [["venue_code", "capacity"]]
        .rename(columns={"capacity": "capacity_fallback"})
    )
    feat_gt = feat_gt.merge(cap_any, on="venue_code", how="left")
    feat_gt["capacity"] = feat_gt["capacity"].combine_first(feat_gt["capacity_fallback"])
    feat_gt = feat_gt.drop(columns=["capacity_fallback"])
    # attendance_ratio is only meaningful from the home team's perspective, but we keep the raw
    # attendance on both rows so future analyses (e.g. away-team-response) have access.
    feat_gt["attendance_ratio"] = np.where(
        (feat_gt["capacity"].notna()) & (feat_gt["capacity"] > 0) & (feat_gt["attendance"].notna()),
        feat_gt["attendance"] / feat_gt["capacity"],
        np.nan,
    )
    feat_gt["attendance_ratio"] = feat_gt["attendance_ratio"].clip(upper=1.05)
    feat_gt["attendance_bucket"] = feat_gt["attendance_ratio"].apply(_bucket)

    # Centered version per team-season (within-team variation)
    feat_gt["team_season_avg_att"] = feat_gt.groupby(["team_id", "season"])["attendance_ratio"].transform("mean")
    feat_gt["attendance_ratio_centered"] = feat_gt["attendance_ratio"] - feat_gt["team_season_avg_att"]

    # Days rest -- days since last game per team (within season)
    feat_gt = feat_gt.sort_values(["team_id", "date"])
    feat_gt["date"] = pd.to_datetime(feat_gt["date"])
    feat_gt["days_rest"] = feat_gt.groupby(["team_id", "season"])["date"].diff().dt.days
    feat_gt["date"] = feat_gt["date"].dt.date.astype(str)

    feat_gt["is_playoff"] = feat_gt["phase_code"].isin(["PO", "FF"]).astype(int)
    feat_gt["is_covid_season"] = (feat_gt["season"] == 2020).astype(int)
    feat_gt["attendance_imputed"] = 0  # we never impute silently

    out = GOLD_DIR / "feat_game_team.parquet"
    feat_gt.to_parquet(out, index=False)

    # ---- feat_team_season_hca ----
    home_rows = feat_gt[feat_gt["is_home"] == 1]
    away_rows = feat_gt[feat_gt["is_home"] == 0]

    agg_home = home_rows.groupby(["team_id", "season"]).agg(
        home_ppg=("team_pts", "mean"),
        home_point_diff=("point_diff", "mean"),
        home_att_ratio=("attendance_ratio", "mean"),
        n_home=("game_id", "count"),
    ).reset_index()
    agg_away = away_rows.groupby(["team_id", "season"]).agg(
        away_ppg=("team_pts", "mean"),
        away_point_diff=("point_diff", "mean"),
        n_away=("game_id", "count"),
    ).reset_index()

    ts_hca = agg_home.merge(agg_away, on=["team_id", "season"], how="outer")
    ts_hca["hca_point_diff"] = ts_hca["home_point_diff"] - ts_hca["away_point_diff"]
    ts_hca.to_parquet(GOLD_DIR / "feat_team_season_hca.parquet", index=False)

    # ---- feat_pairwise_same_opponent ----
    # For every ordered (season, team_a, team_b), compute:
    #   margin_a_home = mean(point_diff | a home vs b)
    #   margin_a_away = mean(point_diff | a away at b) (sign from a's perspective)
    pairs = feat_gt.groupby(["season", "team_id", "opp_team_id", "is_home"])["point_diff"].mean().unstack(
        "is_home"
    ).reset_index().rename(columns={0: "margin_away", 1: "margin_home"})
    pairs = pairs.dropna(subset=["margin_home", "margin_away"])
    pairs["hca_pair_adj"] = pairs["margin_home"] - pairs["margin_away"]
    pairs.to_parquet(GOLD_DIR / "feat_pairwise_same_opponent.parquet", index=False)

    # ---- feat_team_attendance_slope ----
    # Per team: regress point_diff on attendance_ratio over home games only
    from sklearn.linear_model import LinearRegression

    slopes = []
    rng = np.random.default_rng(42)
    for team_id, sub in home_rows.groupby("team_id"):
        mask = sub["attendance_ratio"].notna()
        s = sub[mask]
        if len(s) < 5:
            slopes.append({"team_id": team_id, "slope": float("nan"), "intercept": float("nan"),
                           "n": int(len(s)), "slope_ci_lo": float("nan"), "slope_ci_hi": float("nan")})
            continue
        X = s[["attendance_ratio"]].to_numpy()
        y = s["point_diff"].to_numpy()
        lr = LinearRegression().fit(X, y)
        # Bootstrap slope
        slope_draws = []
        for _ in range(500):
            idx = rng.integers(0, len(s), len(s))
            lr_b = LinearRegression().fit(X[idx], y[idx])
            slope_draws.append(lr_b.coef_[0])
        slopes.append({
            "team_id": team_id,
            "slope": float(lr.coef_[0]),
            "intercept": float(lr.intercept_),
            "n": int(len(s)),
            "slope_ci_lo": float(np.percentile(slope_draws, 2.5)),
            "slope_ci_hi": float(np.percentile(slope_draws, 97.5)),
        })
    pd.DataFrame(slopes).to_parquet(GOLD_DIR / "feat_team_attendance_slope.parquet", index=False)

    counts = {
        "feat_game_team": len(feat_gt),
        "feat_team_season_hca": len(ts_hca),
        "feat_pairwise_same_opponent": len(pairs),
        "feat_team_attendance_slope": len(slopes),
    }
    log.info("gold tables written: %s", counts)
    return counts
