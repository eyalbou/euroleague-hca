"""Phase 5 -- Mechanism analysis.

Answers: WHY is there home-court advantage? Decompose the home edge into
basketball mechanisms (shooting, turnovers, OREB, FT rate, fouls).

Requires: Phase-4 boxscores (fact_game_team_stats enriched with fga/fgm/ftm/etc).

Produces (standalone):
  reports/mechanism_output.json
  dashboards/phase-11-mechanism.html

Also exposes:
  compute_mechanisms() -> dict | None
so the analyst dashboard (scripts/10_analyst_dashboard.py) can render the
Mechanisms tab from live data.
"""
# %% imports
from __future__ import annotations

import json
import logging

import numpy as np
import pandas as pd
from scipy import stats
import statsmodels.api as sm

from euroleague_hca import config
from euroleague_hca.dashboard.render import Dashboard
from euroleague_hca.warehouse import query

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("11_mechanisms")


# ------------------------------------------------------------------
# Importable helper -- used by 10_analyst_dashboard.py
# ------------------------------------------------------------------
def compute_mechanisms() -> dict | None:
    """Return mechanism data in the shape consumed by the Mechanisms tab.

    Returns None when boxscore columns are unavailable (pre-Phase-4).

    Shape:
      {
        "gaps": [{"stat": label, "gap": float, "lo": float, "hi": float,
                  "p": float, "n": int}, ...],
        "contribs": {"eFG%": pts, "FTA/100": pts, "TOV/100": pts, ...},
        "total_hca": float,                # observed mean home margin
        "ols_r2": float,
        "n_games": int,
        "n_team_games": int,
        "ols_intercept": float,
      }
    """
    try:
        fgt_ = query("SELECT * FROM fact_game_team_stats")
    except Exception as e:  # noqa: BLE001
        log.warning("compute_mechanisms: warehouse query failed: %s", e)
        return None
    if fgt_.empty or "fga" not in fgt_.columns or fgt_["fga"].isna().all():
        log.warning("compute_mechanisms: no boxscore columns present")
        return None
    fgt_ = fgt_[fgt_["fga"].notna() & (fgt_["fga"] > 0)].copy()
    if len(fgt_) < 100:
        log.warning("compute_mechanisms: only %d rows -- skipping", len(fgt_))
        return None

    fgt_["tov_per100"] = fgt_["tov"] / fgt_["possessions"].replace(0, np.nan) * 100
    fgt_["ft_rate"] = fgt_["fta"] / fgt_["fga"].replace(0, np.nan)
    if "efg_pct" not in fgt_.columns or fgt_["efg_pct"].isna().all():
        fgt_["efg_pct"] = (fgt_["fgm"] + 0.5 * fgt_["fgm3"]) / fgt_["fga"].replace(0, np.nan)

    # IMPORTANT: integer game_id values repeat across seasons. Pivot on (season, game_id)
    # to keep each game distinct; otherwise ~2500 of 2897 games silently collapse.
    # We use team_pts (silver: matches league HCA +3.78) rather than boxscore `points`
    # which sometimes excludes overtime minutes.
    pivot_ = fgt_.pivot_table(
        index=["season", "game_id"], columns="is_home",
        values=["team_pts", "efg_pct", "ft_rate", "tov_per100", "oreb", "pf"],
        aggfunc="first",
    ).dropna()
    pivot_.columns = [f"{m}_{'home' if h == 1 else 'away'}" for m, h in pivot_.columns]
    pivot_ = pivot_.rename(columns={"team_pts_home": "points_home", "team_pts_away": "points_away"})
    for m in ["points", "efg_pct", "ft_rate", "tov_per100", "oreb", "pf"]:
        pivot_[f"{m}_diff"] = pivot_[f"{m}_home"] - pivot_[f"{m}_away"]

    def _gap(col: str, label: str) -> dict:
        d = pivot_[f"{col}_diff"].dropna().values
        if len(d) == 0:
            return {"stat": label, "gap": 0.0, "lo": 0.0, "hi": 0.0, "p": 1.0, "n": 0}
        rng = np.random.default_rng(7)
        boot = rng.choice(d, size=(2000, len(d)), replace=True).mean(axis=1)
        _, p = stats.ttest_1samp(d, 0.0)
        return {
            "stat": label,
            "gap": float(d.mean()),
            "lo": float(np.percentile(boot, 2.5)),
            "hi": float(np.percentile(boot, 97.5)),
            "p": float(p),
            "n": int(len(d)),
        }

    gaps = [
        _gap("efg_pct", "eFG% (home vs away)"),
        _gap("ft_rate", "FT rate (FTA/FGA)"),
        _gap("tov_per100", "Turnovers per 100"),
        _gap("oreb", "Off. rebounds / game"),
        _gap("pf", "Fouls committed"),
    ]

    y = pivot_["points_diff"].values
    X = pivot_[["efg_pct_diff", "ft_rate_diff", "tov_per100_diff", "oreb_diff", "pf_diff"]].values
    X = sm.add_constant(X)
    ols_ = sm.OLS(y, X).fit()
    coefs = ols_.params.tolist()
    mean_diffs_ = [
        float(pivot_["efg_pct_diff"].mean()),
        float(pivot_["ft_rate_diff"].mean()),
        float(pivot_["tov_per100_diff"].mean()),
        float(pivot_["oreb_diff"].mean()),
        float(pivot_["pf_diff"].mean()),
    ]
    contribs = {
        "eFG%": float(coefs[1] * mean_diffs_[0]),
        "FTA/100": float(coefs[2] * mean_diffs_[1]),
        "TOV/100": float(coefs[3] * mean_diffs_[2]),
        "OREB": float(coefs[4] * mean_diffs_[3]),
        "Foul diff": float(coefs[5] * mean_diffs_[4]),
    }
    return {
        "gaps": gaps,
        "contribs": contribs,
        "total_hca": float(y.mean()),
        "ols_r2": float(ols_.rsquared),
        "n_games": int(len(pivot_)),
        "n_team_games": int(len(fgt_)),
        "ols_intercept": float(coefs[0]),
    }


# ------------------------------------------------------------------
# Standalone execution -- produces JSON report + phase-11 dashboard
# ------------------------------------------------------------------
def _standalone() -> None:  # noqa: C901
    print(config.banner())
    fgt = query("SELECT * FROM fact_game_team_stats")
    log.info("loaded %d rows", len(fgt))

    if "fga" not in fgt.columns or fgt["fga"].isna().all():
        log.error("No boxscore data available -- run scripts/01b_boxscores.py first")
        raise SystemExit(1)

    fgt = fgt[fgt["fga"].notna() & (fgt["fga"] > 0)].copy()
    log.info("after filter: %d team-game rows with boxscore stats", len(fgt))

    fgt["tov_per100"] = fgt["tov"] / fgt["possessions"].replace(0, np.nan) * 100
    fgt["ft_rate"] = fgt["fta"] / fgt["fga"].replace(0, np.nan)
    fgt["pts_per100"] = fgt["points"] / fgt["possessions"].replace(0, np.nan) * 100

    if "efg_pct" not in fgt.columns or fgt["efg_pct"].isna().all():
        fgt["efg_pct"] = (fgt["fgm"] + 0.5 * fgt["fgm3"]) / fgt["fga"].replace(0, np.nan)

    # %% home vs away means on each mechanism
    def boot_mean_ci(values: np.ndarray, n_boot: int = 2000, seed: int = 0) -> tuple[float, float, float]:
        rng = np.random.default_rng(seed)
        vals = np.asarray(values, dtype=float)
        vals = vals[~np.isnan(vals)]
        if len(vals) == 0:
            return (float("nan"), float("nan"), float("nan"))
        boot = rng.choice(vals, size=(n_boot, len(vals)), replace=True).mean(axis=1)
        return (float(vals.mean()), float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5)))

    mechanisms = [
        ("points", "Points per game"),
        ("pts_per100", "Points per 100 possessions (efficiency)"),
        ("efg_pct", "eFG%  (effective field-goal %)"),
        ("ts_pct", "TS%  (true shooting %)"),
        ("fg2_pct", "2-pt FG%"),
        ("fg3_pct", "3-pt FG%"),
        ("ft_pct", "FT%"),
        ("ft_rate", "FT rate (FTA / FGA)"),
        ("tov_per100", "Turnovers per 100 possessions"),
        ("oreb", "Offensive rebounds per game"),
        ("possessions", "Pace (possessions per game)"),
        ("pf", "Personal fouls committed"),
        ("pf_drawn", "Personal fouls drawn"),
    ]

    mechanism_rows = []
    for col, label in mechanisms:
        if col not in fgt.columns:
            continue
        h = fgt[fgt["is_home"] == 1][col].values
        a = fgt[fgt["is_home"] == 0][col].values
        h_mean, h_lo, h_hi = boot_mean_ci(h, seed=11)
        a_mean, a_lo, a_hi = boot_mean_ci(a, seed=22)
        merged = (
            fgt[["season", "game_id", "is_home", col]]
            .pivot_table(index=["season", "game_id"], columns="is_home", values=col, aggfunc="first")
            .dropna()
        )
        if 1 in merged.columns and 0 in merged.columns:
            diffs = (merged[1] - merged[0]).values
        else:
            diffs = np.array([])
        if len(diffs):
            d_mean, d_lo, d_hi = boot_mean_ci(diffs, seed=33)
            try:
                t_stat, p_val = stats.ttest_rel(merged[1], merged[0])
            except Exception:  # noqa: BLE001
                t_stat, p_val = float("nan"), float("nan")
        else:
            d_mean = d_lo = d_hi = float("nan")
            t_stat = p_val = float("nan")

        mechanism_rows.append({
            "metric": col,
            "label": label,
            "home_mean": h_mean, "home_lo": h_lo, "home_hi": h_hi,
            "away_mean": a_mean, "away_lo": a_lo, "away_hi": a_hi,
            "diff_mean": d_mean, "diff_lo": d_lo, "diff_hi": d_hi,
            "n_pairs": int(len(diffs)),
            "t_stat": float(t_stat) if not np.isnan(t_stat) else None,
            "p_value": float(p_val) if not np.isnan(p_val) else None,
        })

    mech_df = pd.DataFrame(mechanism_rows)
    print()
    print("=== HOME vs AWAY MECHANISMS ===")
    print(mech_df[["label", "home_mean", "away_mean", "diff_mean", "p_value"]].to_string(index=False))

    # %% OLS decomposition
    # Pivot on (season, game_id) -- see note above about cross-season game_id collisions.
    # Use team_pts (silver) for the target so observed_hca matches league HCA (+3.78).
    pivot = fgt.pivot_table(
        index=["season", "game_id"], columns="is_home",
        values=["team_pts", "efg_pct", "ft_rate", "tov_per100", "oreb", "pf"],
        aggfunc="first",
    ).dropna()
    pivot.columns = [f"{m}_{'home' if h == 1 else 'away'}" for m, h in pivot.columns]
    pivot = pivot.rename(columns={"team_pts_home": "points_home", "team_pts_away": "points_away"})
    for m in ["points", "efg_pct", "ft_rate", "tov_per100", "oreb", "pf"]:
        pivot[f"{m}_diff"] = pivot[f"{m}_home"] - pivot[f"{m}_away"]

    y = pivot["points_diff"].values
    X = pivot[["efg_pct_diff", "ft_rate_diff", "tov_per100_diff", "oreb_diff", "pf_diff"]].values
    X = sm.add_constant(X)
    feature_names = ["const", "efg_diff", "ftr_diff", "tov_diff", "oreb_diff", "pf_diff"]

    ols = sm.OLS(y, X).fit()
    print()
    print("=== OLS DECOMPOSITION: point_diff ~ mechanism differentials ===")
    print(ols.summary().tables[1])
    log.info("R^2 = %.3f", ols.rsquared)

    coef_rows = []
    for name, b, se, p in zip(feature_names, ols.params, ols.bse, ols.pvalues, strict=False):
        coef_rows.append({
            "feature": name,
            "coef": float(b),
            "se": float(se),
            "lo": float(b - 1.96 * se),
            "hi": float(b + 1.96 * se),
            "p": float(p),
        })

    mean_diffs = {
        "efg_diff": float(pivot["efg_pct_diff"].mean()),
        "ftr_diff": float(pivot["ft_rate_diff"].mean()),
        "tov_diff": float(pivot["tov_per100_diff"].mean()),
        "oreb_diff": float(pivot["oreb_diff"].mean()),
        "pf_diff": float(pivot["pf_diff"].mean()),
    }
    attribution = {}
    for name, coef_row in zip(
        ["efg_diff", "ftr_diff", "tov_diff", "oreb_diff", "pf_diff"],
        coef_rows[1:],
        strict=False,
    ):
        attribution[name] = coef_row["coef"] * mean_diffs[name]
    attribution["constant"] = coef_rows[0]["coef"]
    attribution["observed_hca"] = float(y.mean())

    print()
    print("=== HCA ATTRIBUTION (pts explained per mechanism) ===")
    for k, v in attribution.items():
        print(f"  {k:18s} {v:+.3f} pts")

    # %% persist results
    out_path = config.REPORTS_DIR / "mechanism_output.json"
    out_data = {
        "n_games": int(len(pivot)),
        "n_team_games": int(len(fgt)),
        "seasons": sorted(fgt["season"].unique().tolist()),
        "mechanisms": mechanism_rows,
        "ols": {
            "r_squared": float(ols.rsquared),
            "adj_r_squared": float(ols.rsquared_adj),
            "coefficients": coef_rows,
            "mean_diffs": mean_diffs,
            "attribution": attribution,
        },
    }
    out_path.write_text(json.dumps(out_data, indent=2, default=float))
    log.info("wrote %s", out_path)

    # %% standalone dashboard
    dash = Dashboard(
        title="Phase 5 -- Mechanism analysis",
        slug="phase-11-mechanism",
        subtitle="Home-court advantage decomposed into basketball mechanisms",
    )
    biggest = max(
        ("efg_diff", "tov_diff", "oreb_diff", "ftr_diff", "pf_diff"),
        key=lambda k: abs(attribution[k]),
    )
    dash.kpis = [
        {"label": "Games analyzed", "value": f"{len(pivot):,}"},
        {"label": "OLS R^2", "value": f"{ols.rsquared:.3f}"},
        {"label": "Observed HCA", "value": f"{attribution['observed_hca']:+.2f} pts"},
        {"label": "Biggest driver", "value": biggest,
         "caption": f"{abs(attribution[biggest]):.2f} pts"},
    ]

    dash.add_section(
        "mechanisms", "Home - Away differentials per mechanism",
        "Positive = home teams outperform. Paired on game_id.",
        charts=[{
            "type": "forest", "id": "D11-1",
            "title": "Home - Away differential (paired by game)",
            "teams": [
                {"label": m["label"], "mean": m["diff_mean"],
                 "lo": m["diff_lo"], "hi": m["diff_hi"]}
                for m in mechanism_rows if m["n_pairs"] > 0
            ],
            "xTitle": "home - away (in each metric's own units)",
            "tall": True, "wide": True,
        }],
    )

    attrib_keys = ["efg_diff", "tov_diff", "oreb_diff", "ftr_diff", "pf_diff"]
    dash.add_section(
        "attribution", "HCA attribution -- pts of home edge per mechanism",
        f"OLS decomposition of point_diff. R^2 = {ols.rsquared:.3f}.",
        charts=[{
            "type": "bar", "id": "D11-2",
            "title": "Points of HCA attributable to each mechanism",
            "labels": ["Shooting (eFG)", "Ball security (TOV)", "Off. rebounds",
                       "FT rate", "Foul diff."],
            "datasets": [{
                "label": "pts explained",
                "data": [attribution[k] for k in attrib_keys],
                "colors": ["#4f8cff", "#f5c264", "#7bd8dd", "#a78bfa", "#f87171"],
            }],
            "yTitle": "pts of HCA", "legend": False,
        }],
    )

    dash.write()
    log.info("dashboard written")


if __name__ == "__main__":
    _standalone()
