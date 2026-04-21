"""Phase 19 -- per-referee home-vs-away bias analysis.

For each referee with >= MIN_GAMES assignments:
  1. Compute per-game home-minus-away differentials for fouls called, FT attempts,
     and point margin, averaged across that ref's games.
  2. Bootstrap a 95% CI by resampling the ref's games with replacement 500x.
  3. Compare to the league-wide mean via a z-score (funnel-plot style), produce
     a two-sided p-value, then Holm-correct across all tested refs.

Caveat documented in the writeup: a EuroLeague crew is 3 refs, so an individual
ref's metrics reflect the crew's behavior when that ref is in it. Per-crew
triples are too sparse to analyze directly.

Output:
  reports/referee_output.json  -- per-ref records + summary KPIs
  reports/referee_qa.json      -- invariants for tests

Sample mode limits to the top-N refs by game count for speed during iteration.
"""
from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats as sst

from euroleague_hca import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("19_referee_bias")

MIN_GAMES = 30
N_BOOTSTRAP = 500
RNG = np.random.default_rng(20260421)


@dataclass
class PerRef:
    ref_code: str
    ref_name: str
    ref_country: str
    n_games: int
    mean_pf_diff: float
    lo_pf_diff: float
    hi_pf_diff: float
    mean_fta_diff: float
    lo_fta_diff: float
    hi_fta_diff: float
    mean_home_margin: float
    lo_home_margin: float
    hi_home_margin: float
    z_pf: float
    z_fta: float
    p_pf: float
    p_fta: float
    p_holm_pf: float
    p_holm_fta: float


def _per_game_diffs() -> pd.DataFrame:
    """One row per game with (home_pf - away_pf), (home_fta - away_fta), home_margin."""
    ts = pd.read_parquet(config.SILVER_DIR / "fact_game_team_stats.parquet")
    ts = ts[~ts["is_neutral"].fillna(False)].copy()
    # Pivot home vs away
    ts["side"] = np.where(ts["is_home"] == 1, "home", "away")
    agg = ts.pivot_table(
        index=["season", "game_id"],
        columns="side",
        values=["pf", "fta", "team_pts"],
        aggfunc="first",
    )
    agg.columns = [f"{side}_{metric}" for metric, side in agg.columns]
    agg = agg.reset_index()
    agg["pf_diff"] = agg["home_pf"] - agg["away_pf"]
    agg["fta_diff"] = agg["home_fta"] - agg["away_fta"]
    agg["home_margin"] = agg["home_team_pts"] - agg["away_team_pts"]
    keep = ["season", "game_id", "pf_diff", "fta_diff", "home_margin"]
    out = agg[keep].dropna()
    log.info("per-game diffs: %d games (excluding neutral)", len(out))
    return out


def _bootstrap_mean(values: np.ndarray, n_boot: int = N_BOOTSTRAP) -> tuple[float, float]:
    if len(values) == 0:
        return float("nan"), float("nan")
    idx = RNG.integers(0, len(values), size=(n_boot, len(values)))
    means = values[idx].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def _holm(pvals: list[float]) -> list[float]:
    """Holm-Bonferroni step-down correction. Returns adjusted p-values."""
    m = len(pvals)
    order = np.argsort(pvals)
    adjusted = [1.0] * m
    running_max = 0.0
    for rank, i in enumerate(order):
        adj = pvals[i] * (m - rank)
        running_max = max(running_max, adj)
        adjusted[i] = min(running_max, 1.0)
    return adjusted


def analyze(sample: bool = False) -> dict:
    diffs = _per_game_diffs()
    refs = pd.read_parquet(config.SILVER_DIR / "fact_game_referee.parquet")

    # Long-format join: each (season, game_id) -> 3 ref rows
    merged = refs.merge(diffs, on=["season", "game_id"], how="inner")
    log.info("referee-game rows after join: %d", len(merged))

    # League baselines (per-game)
    league_mu_pf = float(diffs["pf_diff"].mean())
    league_sd_pf = float(diffs["pf_diff"].std(ddof=1))
    league_mu_fta = float(diffs["fta_diff"].mean())
    league_sd_fta = float(diffs["fta_diff"].std(ddof=1))
    league_mu_margin = float(diffs["home_margin"].mean())
    log.info("league baselines: pf_diff mu=%.2f sd=%.2f | fta_diff mu=%.2f sd=%.2f "
             "| home_margin mu=%.2f", league_mu_pf, league_sd_pf,
             league_mu_fta, league_sd_fta, league_mu_margin)

    # Per-ref game counts (dedup at game level since same ref could appear at 2 slots)
    unique_rg = merged.drop_duplicates(subset=["ref_code", "season", "game_id"])
    counts = unique_rg.groupby("ref_code").size().rename("n_games").reset_index()
    eligible = counts[counts["n_games"] >= MIN_GAMES].copy()
    log.info("refs total=%d, eligible (n>=%d)=%d",
             len(counts), MIN_GAMES, len(eligible))

    if sample:
        eligible = eligible.nlargest(10, "n_games").copy()
        log.info("SAMPLE MODE: limiting to top 10 refs by game count")

    ref_names = (
        merged.groupby("ref_code")
        .agg(ref_name=("ref_name", "first"), ref_country=("ref_country", "first"))
        .reset_index()
    )

    per_ref: list[PerRef] = []
    # First pass: compute point estimates + per-test p-values (no Holm yet)
    pvals_pf: list[float] = []
    pvals_fta: list[float] = []
    working: list[dict] = []
    for _, row in eligible.iterrows():
        code = row["ref_code"]
        sub = unique_rg[unique_rg["ref_code"] == code]
        n = len(sub)
        pf = sub["pf_diff"].to_numpy()
        fta = sub["fta_diff"].to_numpy()
        hm = sub["home_margin"].to_numpy()

        mean_pf = float(pf.mean())
        mean_fta = float(fta.mean())
        mean_hm = float(hm.mean())
        lo_pf, hi_pf = _bootstrap_mean(pf)
        lo_fta, hi_fta = _bootstrap_mean(fta)
        lo_hm, hi_hm = _bootstrap_mean(hm)

        # z-scores against league baseline assuming per-game variance (funnel form)
        se_pf = league_sd_pf / np.sqrt(n)
        se_fta = league_sd_fta / np.sqrt(n)
        z_pf = (mean_pf - league_mu_pf) / se_pf if se_pf > 0 else 0.0
        z_fta = (mean_fta - league_mu_fta) / se_fta if se_fta > 0 else 0.0
        p_pf = float(2 * (1 - sst.norm.cdf(abs(z_pf))))
        p_fta = float(2 * (1 - sst.norm.cdf(abs(z_fta))))

        pvals_pf.append(p_pf)
        pvals_fta.append(p_fta)

        name_row = ref_names[ref_names["ref_code"] == code].iloc[0]
        working.append({
            "code": code, "name": name_row["ref_name"],
            "country": name_row["ref_country"], "n": n,
            "mean_pf": mean_pf, "lo_pf": lo_pf, "hi_pf": hi_pf,
            "mean_fta": mean_fta, "lo_fta": lo_fta, "hi_fta": hi_fta,
            "mean_hm": mean_hm, "lo_hm": lo_hm, "hi_hm": hi_hm,
            "z_pf": z_pf, "z_fta": z_fta,
            "p_pf": p_pf, "p_fta": p_fta,
        })

    holm_pf = _holm(pvals_pf)
    holm_fta = _holm(pvals_fta)

    for w, hp, hf in zip(working, holm_pf, holm_fta):
        per_ref.append(PerRef(
            ref_code=w["code"], ref_name=w["name"], ref_country=w["country"],
            n_games=w["n"],
            mean_pf_diff=w["mean_pf"], lo_pf_diff=w["lo_pf"], hi_pf_diff=w["hi_pf"],
            mean_fta_diff=w["mean_fta"], lo_fta_diff=w["lo_fta"], hi_fta_diff=w["hi_fta"],
            mean_home_margin=w["mean_hm"], lo_home_margin=w["lo_hm"], hi_home_margin=w["hi_hm"],
            z_pf=w["z_pf"], z_fta=w["z_fta"],
            p_pf=w["p_pf"], p_fta=w["p_fta"],
            p_holm_pf=float(hp), p_holm_fta=float(hf),
        ))

    # Summary KPIs
    n_sig_raw_pf = sum(1 for r in per_ref if r.p_pf < 0.05)
    n_sig_raw_fta = sum(1 for r in per_ref if r.p_fta < 0.05)
    n_sig_holm_pf = sum(1 for r in per_ref if r.p_holm_pf < 0.05)
    n_sig_holm_fta = sum(1 for r in per_ref if r.p_holm_fta < 0.05)

    # Permutation test -- league-level sanity check on the funnel-plot framing.
    # Under the null (ref has no effect), reshuffle home/away labels within each
    # game, recompute per-ref mean pf_diff, count significant outliers. If our
    # observed count is inside the permutation distribution -> nothing unusual.
    obs_count = n_sig_raw_pf
    perm_counts: list[int] = []
    base_pf = diffs.set_index(["season", "game_id"])["pf_diff"].to_dict()
    n_perms = 200
    for _ in range(n_perms):
        signs = RNG.choice([-1, 1], size=len(diffs))
        perm_map = dict(zip(base_pf.keys(), (np.array(list(base_pf.values())) * signs).tolist()))
        m2 = unique_rg.assign(pf_diff=unique_rg.apply(
            lambda r: perm_map[(r["season"], r["game_id"])], axis=1))
        c = 0
        for code in eligible["ref_code"]:
            sub = m2[m2["ref_code"] == code]["pf_diff"].to_numpy()
            n = len(sub)
            se = league_sd_pf / np.sqrt(n)
            z = sub.mean() / se if se > 0 else 0.0
            if abs(z) > 1.96:
                c += 1
        perm_counts.append(c)
    perm_mean = float(np.mean(perm_counts))
    perm_p = float((sum(c >= obs_count for c in perm_counts) + 1) / (n_perms + 1))

    out = {
        "generated_at": pd.Timestamp.utcnow().isoformat(),
        "baselines": {
            "league_mu_pf_diff": league_mu_pf,
            "league_sd_pf_diff": league_sd_pf,
            "league_mu_fta_diff": league_mu_fta,
            "league_sd_fta_diff": league_sd_fta,
            "league_mu_home_margin": league_mu_margin,
        },
        "kpi": {
            "n_refs_total": int(len(counts)),
            "n_refs_eligible": int(len(eligible)),
            "min_games_threshold": MIN_GAMES,
            "n_significant_raw_pf": int(n_sig_raw_pf),
            "n_significant_raw_fta": int(n_sig_raw_fta),
            "n_significant_holm_pf": int(n_sig_holm_pf),
            "n_significant_holm_fta": int(n_sig_holm_fta),
            "expected_false_positives_raw": round(0.05 * len(eligible), 1),
            "permutation_mean_outlier_count": perm_mean,
            "permutation_p_value": perm_p,
            "n_permutations": n_perms,
            "verdict": (
                "null_result" if n_sig_holm_pf == 0 and n_sig_holm_fta == 0
                else "some_refs_biased"
            ),
        },
        "per_ref": [r.__dict__ for r in sorted(per_ref, key=lambda x: x.p_pf)],
        "funnel": {
            "league_mu": league_mu_pf,
            "sd_per_game": league_sd_pf,
            "ci_k": 1.96,
        },
    }

    out_path = config.REPORTS_DIR / "referee_output.json"
    out_path.write_text(json.dumps(out, indent=2))
    log.info("wrote %s (%.0f KB)", out_path, out_path.stat().st_size / 1024)

    qa = {
        "n_refs_total": int(len(counts)),
        "n_refs_eligible": int(len(eligible)),
        "all_refs_have_country": bool(all(r.ref_country for r in per_ref)),
        "p_values_in_range": all(0 <= r.p_pf <= 1 and 0 <= r.p_fta <= 1 for r in per_ref),
        "holm_monotone": all(r.p_holm_pf >= r.p_pf for r in per_ref),
        "verdict_matches_holm": (
            out["kpi"]["verdict"] == "null_result"
            if out["kpi"]["n_significant_holm_pf"] == 0
               and out["kpi"]["n_significant_holm_fta"] == 0
            else True
        ),
    }
    (config.REPORTS_DIR / "referee_qa.json").write_text(json.dumps(qa, indent=2))
    log.info("QA: %s", qa)
    log.info("VERDICT: %s  (raw sig PF=%d, Holm PF=%d)",
             out["kpi"]["verdict"],
             out["kpi"]["n_significant_raw_pf"],
             out["kpi"]["n_significant_holm_pf"])
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true")
    args = ap.parse_args()
    analyze(sample=args.sample)


if __name__ == "__main__":
    main()
