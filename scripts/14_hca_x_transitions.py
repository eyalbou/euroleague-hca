"""Phase 14 -- HCA x Transitions interaction.

The original HCA question asks "does playing at home change outcomes, and by
how much?" The transition analysis asks "what typically follows action X?"
This script connects them: for each source action X, is there a home-team
advantage *inside the possession-level dynamics* that follow X?

Concretely, for each PRIMARY_SOURCE we compute:
  - home_ppp    : mean PPP on team A's next offensive possession, when A was the home team at source time
  - away_ppp    : same, when A was the away team
  - delta_ppp   : home_ppp - away_ppp with cluster-bootstrap 95% CI at game level
  - JSD(home||away) on Q1 distribution (how different are the opponent-response
    distributions themselves when source is home vs away)
  - frequency_per_game : how often X happens per game (context for attribution)

Then an attribution waterfall: rank sources by
    contribution = frequency_per_game * delta_ppp
which is a first-order estimate of how many points per game each source
contributes to the league-wide HCA.

Outputs:
  reports/hca_transitions.json   -- per-source payload + waterfall + headline KPIs
"""
# %% imports
from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from euroleague_hca import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("14_hca_x_transitions")


# %% constants (mirror 12_transitions)

PRIMARY_SOURCES = [
    "3FGM", "3FGA", "2FGM", "2FGA", "FTM", "FTA",
    "AS", "TO", "D", "O", "ST",
    "FV", "AG",
    "CM", "RV", "OF", "CMU", "CMT",
]

PLAIN_LABELS = {
    "3FGM": "Made 3-pointer",  "3FGA": "Missed 3-pointer",
    "2FGM": "Made 2-pointer",  "2FGA": "Missed 2-pointer",
    "FTM":  "Made free throw", "FTA":  "Missed free throw",
    "AS":   "Assist",          "TO":   "Turnover",
    "D":    "Defensive rebound", "O":  "Offensive rebound",
    "ST":   "Steal",           "FV":  "Block (defender)",
    "AG":   "Shot blocked (shooter)",
    "CM":   "Foul committed",  "RV":  "Foul drawn",
    "OF":   "Offensive foul",  "CMU": "Unsportsmanlike foul",
    "CMT":  "Technical foul",
}

OFFENSIVE_ACTIONS = {"2FGM", "2FGA", "3FGM", "3FGA", "FTM", "FTA", "TO", "OF"}
MIN_N = 100      # higher floor than phase-12 because we're splitting home/away
BOOTSTRAP = 500
SEED = 42


# %% load events + add transition cols (reuse phase-12 logic)

def load_events() -> pd.DataFrame:
    events = pd.read_parquet(config.SILVER_DIR / "fact_game_event.parquet")
    keep = events[events["is_action"] == 1].copy()
    keep = keep.sort_values(["season", "game_id", "event_idx"]).reset_index(drop=True)
    log.info("loaded %d in-play events across %d games",
             len(keep), keep.groupby(["season", "game_id"]).ngroups)
    return keep


def _parse_cum_seconds(period: int, mt) -> float:
    if mt is None:
        return np.nan
    s = str(mt).strip()
    if ":" not in s:
        return np.nan
    try:
        mm, ss = s.split(":")
        remaining = int(mm) * 60 + int(ss)
    except Exception:
        return np.nan
    if period <= 4:
        return (period - 1) * 600 + (600 - remaining)
    return 2400 + (period - 5) * 300 + (300 - remaining)


def _compute_next_cols_for_game(g: pd.DataFrame) -> pd.DataFrame:
    team = g["code_team"].values
    act = g["action_type"].values
    is_home_arr = g["is_home"].values
    period_arr = g["period"].values
    mt_arr = g["marker_time"].values
    pts_h_ff = pd.Series(g["points_home"].values).ffill().fillna(0).values
    pts_a_ff = pd.Series(g["points_away"].values).ffill().fillna(0).values
    n = len(g)

    next_q1 = np.full(n, None, dtype=object)
    next_q2 = np.full(n, None, dtype=object)
    ppp_q2 = np.full(n, np.nan)

    # Q1
    for i in range(n - 1, -1, -1):
        t = team[i]
        if t is None:
            continue
        for j in range(i + 1, n):
            if team[j] is not None and team[j] != t:
                next_q1[i] = act[j]
                break

    # Q2 with PPP
    unique_teams = [t for t in pd.unique(team) if t is not None]
    my_off_idx: dict = {}
    opp_idx_by_team: dict = {}
    is_off = np.array([a in OFFENSIVE_ACTIONS for a in act])
    for t in unique_teams:
        my_off_idx[t] = np.where((team == t) & is_off)[0]
        opp_idx_by_team[t] = np.where(
            np.array([(tt is not None) and (tt != t) for tt in team])
        )[0]

    for i in range(n):
        t = team[i]
        if t is None:
            continue
        opps = opp_idx_by_team[t]
        next_opp_arr = opps[opps > i]
        if next_opp_arr.size == 0:
            continue
        first_opp = next_opp_arr[0]
        mine = my_off_idx[t]
        next_mine = mine[mine > first_opp]
        if next_mine.size == 0:
            continue
        F = int(next_mine[0])
        next_q2[i] = act[F]

        opps_after_F = opps[opps > F]
        H = int(opps_after_F[0]) if opps_after_F.size > 0 else -1
        is_h = is_home_arr[i]
        if is_h == 1:
            pts_A = pts_h_ff
        elif is_h == 0:
            pts_A = pts_a_ff
        else:
            continue
        pts_before = float(pts_A[F - 1]) if F > 0 else 0.0
        if H > 0:
            pts_after = float(pts_A[H - 1])
        else:
            pts_after = float(pts_A[-1])
        ppp_q2[i] = pts_after - pts_before

    g = g.copy()
    g["next_q1"] = next_q1
    g["next_q2"] = next_q2
    g["ppp_q2"] = ppp_q2
    return g


def add_transition_columns(events: pd.DataFrame) -> pd.DataFrame:
    out_parts = []
    i = 0
    total = events.groupby(["season", "game_id"]).ngroups
    for (_s, _gid), g in events.groupby(["season", "game_id"], sort=False):
        out_parts.append(_compute_next_cols_for_game(g))
        i += 1
        if i % 200 == 0:
            log.info("  enrich progress: %d/%d games", i, total)
    return pd.concat(out_parts, ignore_index=True)


# %% distributions / divergence

def _distribution(series: pd.Series) -> dict:
    cleaned = series.dropna()
    n = len(cleaned)
    if n == 0:
        return {}
    c = Counter(cleaned)
    return {k: v / n for k, v in c.items()}


def _jsd(p: dict, q: dict, eps: float = 1e-6) -> float:
    """Jensen-Shannon divergence in bits (symmetric, 0..1)."""
    actions = set(p) | set(q)
    m = {a: 0.5 * (p.get(a, 0.0) + q.get(a, 0.0)) for a in actions}

    def _kl(u, v):
        s = 0.0
        for a in actions:
            ua = u.get(a, 0.0)
            va = v.get(a, 0.0) + eps
            if ua > 0:
                s += ua * np.log2(ua / va)
        return s

    return float(0.5 * _kl(p, m) + 0.5 * _kl(q, m))


# %% cluster-bootstrap delta PPP

def _bootstrap_delta_ppp(
    home_rows: pd.DataFrame, away_rows: pd.DataFrame,
    n_resamples: int = BOOTSTRAP, seed: int = SEED,
) -> dict:
    """Game-level cluster bootstrap on (home_ppp - away_ppp)."""
    rng = np.random.default_rng(seed)

    def _game_map(df):
        return df.groupby(["season", "game_id"])["ppp_q2"].apply(
            lambda s: s.dropna().tolist()
        ).to_dict()

    h = _game_map(home_rows)
    a = _game_map(away_rows)
    hk = list(h.keys())
    ak = list(a.keys())

    def _mean_or_nan(lst):
        return float(np.mean(lst)) if lst else np.nan

    home_mean = _mean_or_nan([v for lst in h.values() for v in lst])
    away_mean = _mean_or_nan([v for lst in a.values() for v in lst])
    delta = home_mean - away_mean if (not np.isnan(home_mean) and not np.isnan(away_mean)) else np.nan

    deltas = []
    if hk and ak:
        for _ in range(n_resamples):
            hs = rng.integers(0, len(hk), size=len(hk))
            as_ = rng.integers(0, len(ak), size=len(ak))
            hv = [v for k in hs for v in h[hk[k]]]
            av = [v for k in as_ for v in a[ak[k]]]
            if hv and av:
                deltas.append(float(np.mean(hv) - np.mean(av)))

    if deltas:
        lo, hi = float(np.quantile(deltas, 0.025)), float(np.quantile(deltas, 0.975))
    else:
        lo, hi = float("nan"), float("nan")

    return {
        "home_ppp": round(home_mean, 4) if not np.isnan(home_mean) else None,
        "away_ppp": round(away_mean, 4) if not np.isnan(away_mean) else None,
        "delta_ppp": round(delta, 4) if not np.isnan(delta) else None,
        "lo": round(lo, 4) if not np.isnan(lo) else None,
        "hi": round(hi, 4) if not np.isnan(hi) else None,
        "n_home": int(home_rows["ppp_q2"].notna().sum()),
        "n_away": int(away_rows["ppp_q2"].notna().sum()),
    }


# %% main pipeline

def build(events: pd.DataFrame) -> dict:
    log.info("enriching per-game transitions + PPP...")
    events = add_transition_columns(events)

    n_games = int(events.groupby(["season", "game_id"]).ngroups)

    # Source-level home/away comparison on Q2 PPP + Q1 JSD
    per_source = []
    for src in PRIMARY_SOURCES:
        sub_home = events[(events["action_type"] == src) & (events["is_home"] == 1)]
        sub_away = events[(events["action_type"] == src) & (events["is_home"] == 0)]
        if len(sub_home) < MIN_N or len(sub_away) < MIN_N:
            continue

        ppp = _bootstrap_delta_ppp(sub_home, sub_away)
        freq_per_game_home = len(sub_home) / n_games
        freq_per_game_away = len(sub_away) / n_games
        freq_per_game = (len(sub_home) + len(sub_away)) / n_games

        # Jensen-Shannon on Q1 distributions
        dh_q1 = _distribution(sub_home["next_q1"])
        da_q1 = _distribution(sub_away["next_q1"])
        jsd_q1 = _jsd(dh_q1, da_q1) if dh_q1 and da_q1 else None

        # Top-1 Q1 home vs away (for the dashboard overlay summary)
        top_home_q1 = max(dh_q1.items(), key=lambda kv: kv[1]) if dh_q1 else (None, 0.0)
        top_away_q1 = max(da_q1.items(), key=lambda kv: kv[1]) if da_q1 else (None, 0.0)

        # contribution = freq * delta_ppp (first-order attribution)
        contrib = None
        if ppp["delta_ppp"] is not None:
            contrib = round(freq_per_game * ppp["delta_ppp"], 4)

        per_source.append({
            "source": src,
            "source_label": PLAIN_LABELS.get(src, src),
            "n_home": ppp["n_home"],
            "n_away": ppp["n_away"],
            "home_ppp": ppp["home_ppp"],
            "away_ppp": ppp["away_ppp"],
            "delta_ppp": ppp["delta_ppp"],
            "delta_lo": ppp["lo"],
            "delta_hi": ppp["hi"],
            "jsd_q1": round(jsd_q1, 4) if jsd_q1 is not None else None,
            "freq_per_game": round(freq_per_game, 3),
            "freq_per_game_home": round(freq_per_game_home, 3),
            "freq_per_game_away": round(freq_per_game_away, 3),
            "top_home_q1": {"action": top_home_q1[0], "p": round(top_home_q1[1], 4)},
            "top_away_q1": {"action": top_away_q1[0], "p": round(top_away_q1[1], 4)},
            "contribution_pts_per_game": contrib,
        })

    # Ranking by |delta_ppp| (per-possession edge), with a volume-weighted
    # attribution. We can NOT simply sum contribution_pts_per_game across sources:
    # a missed 2 and its defensive rebound both lead to the same next possession,
    # so per-source contributions double- / triple-count. Instead compute the
    # volume-weighted mean delta_ppp and translate it to pts/game using the
    # league's possessions-per-team-per-game (estimated below from FGA+TO).
    ranked = [r for r in per_source if r["delta_ppp"] is not None]
    ranked.sort(key=lambda r: -abs(r["delta_ppp"]))
    # "Waterfall" view = rank by |delta_ppp| -- for visual decomposition only;
    # cumulative field is informational, NOT an attribution total.
    waterfall = [{
        "source": r["source"],
        "source_label": r["source_label"],
        "contribution": r["contribution_pts_per_game"],
        "delta_ppp": r["delta_ppp"],
        "delta_lo": r["delta_lo"],
        "delta_hi": r["delta_hi"],
        "freq_per_game": r["freq_per_game"],
        "n_home": r["n_home"],
        "n_away": r["n_away"],
    } for r in ranked]

    # Volume-weighted mean delta_ppp (weight = total observations per source)
    total_n = sum((r["n_home"] + r["n_away"]) for r in ranked)
    weighted_delta = (
        sum(r["delta_ppp"] * (r["n_home"] + r["n_away"]) for r in ranked) / total_n
        if total_n > 0 else 0.0
    )

    # Estimated possessions per team per game, using possession-ending sources
    # (FGM / FGA + TO). Each is counted once per possession.
    poss_sources = {"2FGM", "2FGA", "3FGM", "3FGA", "TO"}
    poss_per_game_total = sum(
        r["freq_per_game"] for r in per_source if r["source"] in poss_sources
    )
    poss_per_team_per_game = poss_per_game_total / 2.0  # each possession belongs to one team

    # HCA attributable to possession-level efficiency:
    # HCA_poss = poss_per_team_per_game * weighted_delta_ppp
    # (home team scores weighted_delta more pts per possession than away team on
    # its own possessions; same for away team -- delta is about how the team
    # performs when at home vs on the road on ITS possession.)
    hca_from_poss = poss_per_team_per_game * weighted_delta
    # Published HCA from mixedlm intercept is ~3.86 pts/game
    hca_observed = 3.86
    share_explained = hca_from_poss / hca_observed if hca_observed else None

    # Top sources (positive delta_ppp): where home team scores more after X
    top_advantage = sorted(
        [r for r in per_source if r["delta_ppp"] is not None and r["delta_ppp"] > 0],
        key=lambda r: -r["delta_ppp"],
    )[:5]
    # Biggest home->away DIFFERENCE in style (JSD-ranked)
    top_style = sorted(
        [r for r in per_source if r["jsd_q1"] is not None],
        key=lambda r: -r["jsd_q1"],
    )[:5]

    return {
        "n_games": n_games,
        "n_events": int(len(events)),
        "per_source": per_source,
        "waterfall": waterfall,
        "kpi": {
            "n_sources": len(per_source),
            "weighted_delta_ppp": round(float(weighted_delta), 4),
            "poss_per_team_per_game": round(float(poss_per_team_per_game), 2),
            "hca_from_possession_efficiency_pts": round(float(hca_from_poss), 3),
            "hca_observed_pts": hca_observed,
            "share_of_hca_explained": round(float(share_explained), 3) if share_explained else None,
            "top_home_advantage_source": ranked[0]["source"] if ranked else None,
            "top_home_advantage_delta": ranked[0]["delta_ppp"] if ranked else None,
            "pct_sources_positive_delta": round(
                sum(1 for r in ranked if r["delta_ppp"] > 0) / len(ranked), 3
            ) if ranked else 0.0,
        },
        "top_advantage": top_advantage,
        "top_style": top_style,
        "plain_labels": PLAIN_LABELS,
    }


def qa_checks(out: dict) -> dict:
    checks = {}
    deltas = [r["delta_ppp"] for r in out["per_source"] if r["delta_ppp"] is not None]
    checks["delta_ppp_range"] = {
        "min": round(min(deltas), 3), "max": round(max(deltas), 3),
        "expect": "most deltas in [-0.10, +0.10] -- a few outliers OK",
    }
    pos = [d for d in deltas if d > 0]
    checks["sign_majority"] = {
        "pos_share": round(len(pos) / len(deltas), 3),
        "expect": "> 0.50 if home teams hold an edge on most possessions",
    }
    checks["hca_from_possession_efficiency"] = {
        "pts_per_game": out["kpi"]["hca_from_possession_efficiency_pts"],
        "share_of_hca": out["kpi"]["share_of_hca_explained"],
        "expect": "pts in [1.0, 3.5]; share in [0.30, 0.90] -- rest is pace / FTA rate",
    }
    return checks


def main() -> None:
    events = load_events()
    out = build(events)
    out["qa"] = qa_checks(out)

    out_path = config.REPORTS_DIR / "hca_transitions.json"
    out_path.write_text(json.dumps(out, indent=2))
    log.info("wrote %s (%.0f KB)", out_path, out_path.stat().st_size / 1024)
    log.info("QA:\n%s", json.dumps(out["qa"], indent=2))
    log.info("top-5 home-advantage sources:")
    for r in out["top_advantage"]:
        log.info("  %-6s delta_ppp=%+.3f  freq=%.2f/game  top_home=%s (%.2f) vs top_away=%s (%.2f)",
                 r["source"], r["delta_ppp"], r["freq_per_game"],
                 r["top_home_q1"]["action"], r["top_home_q1"]["p"],
                 r["top_away_q1"]["action"], r["top_away_q1"]["p"])


if __name__ == "__main__":
    main()
