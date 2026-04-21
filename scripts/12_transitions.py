"""Phase 12 -- Play-by-play transition analysis.

For each primary "source" action X, compute three different "next action" distributions:

  Q0  raw next in-play event, any team
  Q1  opponent's immediate next in-play action
  Q2  same team's first in-play action on their next offensive possession
      (approximation: first same-team OFFENSIVE action that has at least one
       intervening opponent action -- so offensive rebounds inside the same
       possession are correctly skipped)

Each distribution is computed:
  - overall (split='all')
  - split='home_acting' / 'away_acting'  (using is_home of the source event)
  - split='open_doors'  / 'closed_doors' (using attendance==0 flag on the game)

Per-source concentration metrics (Shannon entropy, Gini) are reported alongside.

Enrichments (v2, added by the "improvements" pass):
  - baseline P(next_action) per (question, split) + lift = p / baseline per bar
  - PPP (points-per-possession on team A's NEXT offensive possession) for Q2
  - median seconds to next event for Q1 and Q2
  - per-team distinctiveness ranking: KL-divergence of each team's Q2 from league
  - paired-event flag for sources where the raw log double-books (FV/AG, CM/RV)

Outputs:
  reports/transitions_bars.json          -- drives per-source horizontal bar charts
  reports/transitions_concentration.json -- entropy + Gini + PPP + time per (src,q,split)
  reports/transitions_heatmap.json       -- source x next matrix for the heatmap
  reports/transitions_top1.csv           -- flat top-1 summary table
  reports/transitions_qa.json            -- smoke-check numbers for the plan validation
  reports/transitions_team_rank.json     -- per-source, most/least distinctive teams (Q2)
"""
# %% imports
from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from euroleague_hca import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("12_transitions")


# %% constants

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

# Grouping used by the dashboard dropdown; also embedded into the output.
SOURCE_CATEGORIES = {
    "Shots": ["3FGM", "3FGA", "2FGM", "2FGA", "FTM", "FTA"],
    "Rebounds": ["D", "O"],
    "Playmaking": ["AS", "TO"],
    "Defense": ["ST", "FV"],
    "Shooter receiving block": ["AG"],
    "Fouls": ["CM", "RV", "OF", "CMU", "CMT"],
}

# Sources where the RAW LOG double-books each physical event from both sides.
# A single "blocked shot" is recorded twice: AG from the shooter's side and FV
# from the defender's side. Same for CM (foul committed) / RV (foul drawn).
# This inflates Q1 (opponent's next action) in a way that looks spectacular
# but is just a data-logging convention. The dashboard surfaces a warning.
PAIRED_SOURCES = {
    "FV": "AG",   # block by defender  -> shooter logged as blocked
    "AG": "FV",
    "CM": "RV",   # foul committed     -> foul drawn
    "RV": "CM",
    "OF": "CM",   # offensive foul     -> defender logged as drawing it
}

TOP_K = 8
BOOTSTRAP = 500
SEED = 42
MIN_N = 30
MIN_N_TEAM = 50  # per-team ranking requires denser data per source

OFFENSIVE_ACTIONS = {"2FGM", "2FGA", "3FGM", "3FGA", "FTM", "FTA", "TO", "OF"}


# %% data loading

def load_events() -> pd.DataFrame:
    events = pd.read_parquet(config.SILVER_DIR / "fact_game_event.parquet")
    keep = events[events["is_action"] == 1].copy()
    keep = keep.sort_values(["season", "game_id", "event_idx"]).reset_index(drop=True)
    log.info("loaded %d in-play events across %d games",
             len(keep), keep.groupby(["season", "game_id"]).ngroups)
    return keep


# %% transition computation

def _parse_cum_seconds(period: int, mt) -> float:
    """Convert (period, 'mm:ss' countdown) into cumulative game seconds elapsed.

    EuroLeague: 4x10 min regular periods, 5-min OTs (period 5+).
    Returns NaN if parsing fails.
    """
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
    """Per-game: add next_q0/next_q1/next_q2, plus ppp_q2, sec_q1, sec_q2."""
    team = g["code_team"].values
    act = g["action_type"].values
    is_home_arr = g["is_home"].values
    period_arr = g["period"].values
    mt_arr = g["marker_time"].values
    pts_h_ff = pd.Series(g["points_home"].values).ffill().fillna(0).values
    pts_a_ff = pd.Series(g["points_away"].values).ffill().fillna(0).values
    n = len(g)

    cum_sec = np.array(
        [_parse_cum_seconds(period_arr[i], mt_arr[i]) for i in range(n)]
    )

    next_q0 = np.full(n, None, dtype=object)
    next_q1 = np.full(n, None, dtype=object)
    next_q2 = np.full(n, None, dtype=object)
    ppp_q2 = np.full(n, np.nan)
    sec_q1 = np.full(n, np.nan)
    sec_q2 = np.full(n, np.nan)

    # Q0: immediate next
    next_q0[:-1] = act[1:]

    # Q1: for each i, first j>i where team[j]!=team[i] (both non-null)
    for i in range(n - 1, -1, -1):
        t = team[i]
        if t is None:
            continue
        for j in range(i + 1, n):
            if team[j] is not None and team[j] != t:
                next_q1[i] = act[j]
                if not np.isnan(cum_sec[i]) and not np.isnan(cum_sec[j]):
                    sec_q1[i] = max(0.0, cum_sec[j] - cum_sec[i])
                break

    # Q2: first same-team OFFENSIVE action with at least one intervening opponent action
    unique_teams = [t for t in pd.unique(team) if t is not None]
    my_off_idx: dict[str, np.ndarray] = {}
    opp_idx_by_team: dict[str, np.ndarray] = {}
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
        if not np.isnan(cum_sec[i]) and not np.isnan(cum_sec[F]):
            sec_q2[i] = max(0.0, cum_sec[F] - cum_sec[i])

        # PPP on A's next offensive possession: H = first opp action after F
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
    g["next_q0"] = next_q0
    g["next_q1"] = next_q1
    g["next_q2"] = next_q2
    g["ppp_q2"] = ppp_q2
    g["sec_q1"] = sec_q1
    g["sec_q2"] = sec_q2
    return g


def add_transition_columns(events: pd.DataFrame) -> pd.DataFrame:
    out_parts = []
    i = 0
    total = events.groupby(["season", "game_id"]).ngroups
    for (_s, _gid), g in events.groupby(["season", "game_id"], sort=False):
        out_parts.append(_compute_next_cols_for_game(g))
        i += 1
        if i % 200 == 0:
            log.info("  next-cols progress: %d/%d games", i, total)
    return pd.concat(out_parts, ignore_index=True)


# %% distribution + bootstrap

def _distribution(next_actions: pd.Series) -> dict[str, float]:
    cleaned = next_actions.dropna()
    n = len(cleaned)
    if n == 0:
        return {}
    c = Counter(cleaned)
    return {k: v / n for k, v in c.items()}


def _topk_with_other(dist: dict[str, float], k: int = TOP_K) -> list[dict]:
    if not dist:
        return []
    sorted_items = sorted(dist.items(), key=lambda kv: -kv[1])
    top = sorted_items[:k]
    rest = sorted_items[k:]
    rest_p = sum(p for _, p in rest)
    out = [{"next_action": a, "p": p} for a, p in top]
    if rest_p > 0:
        out.append({"next_action": "Other", "p": rest_p})
    return out


def _entropy_bits(dist: dict[str, float]) -> float:
    if not dist:
        return 0.0
    ps = np.array(list(dist.values()))
    ps = ps[ps > 0]
    return float(-(ps * np.log2(ps)).sum())


def _gini(dist: dict[str, float]) -> float:
    if not dist:
        return 0.0
    ps = np.sort(np.array(list(dist.values())))
    n = len(ps)
    if n == 0 or ps.sum() == 0:
        return 0.0
    cum = np.cumsum(ps)
    return float((n + 1 - 2 * cum.sum() / ps.sum()) / n)


def _kl_divergence(p: dict[str, float], q: dict[str, float], eps: float = 1e-6) -> float:
    """KL(p || q): how much p (team) diverges from q (league). Smoothed by eps."""
    actions = set(p) | set(q)
    s = 0.0
    for a in actions:
        pa = p.get(a, 0.0)
        qa = q.get(a, 0.0) + eps
        if pa > 0:
            s += pa * np.log2(pa / qa)
    return float(s)


def _bootstrap_ci_for_topk(
    sub: pd.DataFrame, next_col: str, top_actions: list[str],
    n_resamples: int = BOOTSTRAP, seed: int = SEED,
) -> dict[str, tuple[float, float]]:
    rng = np.random.default_rng(seed)
    games = sub.groupby(["season", "game_id"])[next_col].apply(
        lambda s: s.dropna().tolist()
    ).to_dict()
    game_keys = list(games.keys())
    if not game_keys:
        return {a: (0.0, 0.0) for a in top_actions}

    boot_ps: dict[str, list[float]] = {a: [] for a in top_actions}
    n_games = len(game_keys)
    for _ in range(n_resamples):
        idx = rng.integers(0, n_games, size=n_games)
        sampled: list[str] = []
        for k in idx:
            sampled.extend(games[game_keys[k]])
        if not sampled:
            continue
        c = Counter(sampled)
        total = len(sampled)
        for a in top_actions:
            boot_ps[a].append(c.get(a, 0) / total)

    ci = {}
    for a, ps in boot_ps.items():
        if ps:
            ci[a] = (float(np.quantile(ps, 0.025)), float(np.quantile(ps, 0.975)))
        else:
            ci[a] = (0.0, 0.0)
    return ci


# %% baselines (marginal P(next) per split, per question)

def _compute_baselines(events: pd.DataFrame) -> dict:
    """Overall P(action) per (split, question) -- used for lift = p / baseline."""
    splits = {
        "all":          events,
        "home_acting":  events[events["is_home"] == 1],
        "away_acting":  events[events["is_home"] == 0],
        "open_doors":   events[events["closed_doors"] == 0],
        "closed_doors": events[events["closed_doors"] == 1],
    }
    out: dict = {}
    for split, df in splits.items():
        out[split] = {}
        for q, col in [("q0", "next_q0"), ("q1", "next_q1"), ("q2", "next_q2")]:
            d = _distribution(df[col])
            out[split][q] = d
    return out


# %% per-team distinctiveness (Q2, split='all')

def _compute_team_rankings(events: pd.DataFrame) -> dict:
    """Per source action: ranking of teams by Q2 KL-divergence from league."""
    out: dict = {}
    for src in PRIMARY_SOURCES:
        src_rows = events[events["action_type"] == src]
        league_dist = _distribution(src_rows["next_q2"])
        if not league_dist or len(src_rows.dropna(subset=["next_q2"])) < 200:
            continue
        league_top3 = _topk_with_other(league_dist, k=3)
        teams_payload = []
        for team_id, grp in src_rows.groupby("code_team"):
            n_team = grp["next_q2"].notna().sum()
            if n_team < MIN_N_TEAM:
                continue
            team_dist = _distribution(grp["next_q2"])
            kl = _kl_divergence(team_dist, league_dist)
            top = _topk_with_other(team_dist, k=3)
            teams_payload.append({
                "team": team_id,
                "n": int(n_team),
                "kl_div": round(kl, 4),
                "top3": [
                    {"next_action": b["next_action"], "p": round(b["p"], 4)}
                    for b in top[:3]
                ],
                "top1_action": top[0]["next_action"] if top else None,
                "top1_p": round(top[0]["p"], 4) if top else 0.0,
            })
        teams_payload.sort(key=lambda r: -r["kl_div"])
        out[src] = {
            "source_label": PLAIN_LABELS.get(src, src),
            "league": [
                {"next_action": b["next_action"], "p": round(b["p"], 4)}
                for b in league_top3
            ],
            "teams": teams_payload,
        }
    return out


# %% main pipeline

def build_transitions(events: pd.DataFrame) -> dict:
    log.info("computing next-action columns per game...")
    events = add_transition_columns(events)

    log.info("computing baselines (marginal P(next) per split)...")
    baselines = _compute_baselines(events)

    log.info("computing per-team rankings...")
    team_rankings = _compute_team_rankings(events)

    splits = {
        "all":          events,
        "home_acting":  events[events["is_home"] == 1],
        "away_acting":  events[events["is_home"] == 0],
        "open_doors":   events[events["closed_doors"] == 0],
        "closed_doors": events[events["closed_doors"] == 1],
    }

    question_cols = {"q0": "next_q0", "q1": "next_q1", "q2": "next_q2"}
    time_cols = {"q1": "sec_q1", "q2": "sec_q2"}

    bars: list[dict] = []
    concentration: list[dict] = []
    heatmap: list[dict] = []
    top1: list[dict] = []

    for split_name, df_split in splits.items():
        for src in PRIMARY_SOURCES:
            src_rows = df_split[df_split["action_type"] == src]
            n_src = len(src_rows)
            if n_src < MIN_N:
                continue

            for q_key, col in question_cols.items():
                dist = _distribution(src_rows[col])
                n_obs = int(src_rows[col].notna().sum())
                if n_obs < MIN_N:
                    continue

                top_bars = _topk_with_other(dist)
                top_action_names = [
                    b["next_action"] for b in top_bars if b["next_action"] != "Other"
                ]
                cis = _bootstrap_ci_for_topk(src_rows, col, top_action_names)

                baseline_for_q = baselines.get(split_name, {}).get(q_key, {})

                for rank, bar in enumerate(top_bars):
                    lo, hi = cis.get(bar["next_action"], (0.0, 0.0))
                    if bar["next_action"] == "Other":
                        base_p = 0.0
                        lift = 1.0
                    else:
                        base_p = float(baseline_for_q.get(bar["next_action"], 0.0))
                        lift = (bar["p"] / base_p) if base_p > 0 else float("nan")
                    bars.append({
                        "source": src, "source_label": PLAIN_LABELS.get(src, src),
                        "question": q_key, "split": split_name,
                        "rank": rank, "next_action": bar["next_action"],
                        "p": round(float(bar["p"]), 4),
                        "baseline_p": round(base_p, 4),
                        "lift": None if np.isnan(lift) else round(float(lift), 3),
                        "lo": round(lo, 4), "hi": round(hi, 4),
                        "n": n_obs,
                    })

                # Concentration row + PPP + time-to-next
                conc_row: dict = {
                    "source": src, "question": q_key, "split": split_name,
                    "n": n_obs, "n_source_events": int(n_src),
                    "entropy_bits": round(_entropy_bits(dist), 4),
                    "gini": round(_gini(dist), 4),
                    "top1_action": top_bars[0]["next_action"] if top_bars else None,
                    "top1_p": round(top_bars[0]["p"], 4) if top_bars else 0.0,
                }
                if q_key in time_cols:
                    sec = src_rows[time_cols[q_key]].dropna()
                    if len(sec) >= MIN_N:
                        conc_row["median_sec"] = round(float(sec.median()), 2)
                        conc_row["p10_sec"] = round(float(sec.quantile(0.10)), 2)
                        conc_row["p90_sec"] = round(float(sec.quantile(0.90)), 2)
                if q_key == "q2":
                    ppp = src_rows["ppp_q2"].dropna()
                    if len(ppp) >= MIN_N:
                        conc_row["ppp_mean"] = round(float(ppp.mean()), 3)
                        conc_row["ppp_n"] = int(len(ppp))
                concentration.append(conc_row)

                if split_name == "all":
                    for next_a, p in dist.items():
                        heatmap.append({
                            "source": src, "question": q_key,
                            "next_action": next_a, "p": round(float(p), 4),
                            "baseline_p": round(float(baseline_for_q.get(next_a, 0.0)), 4),
                            "lift": (
                                round(float(p / baseline_for_q[next_a]), 3)
                                if baseline_for_q.get(next_a, 0) > 0 else None
                            ),
                            "n": n_obs,
                        })

                if top_bars:
                    top1.append({
                        "source": src, "question": q_key, "split": split_name,
                        "top1_action": top_bars[0]["next_action"],
                        "p": round(top_bars[0]["p"], 4),
                        "n": n_obs,
                    })

    return {
        "bars": bars,
        "concentration": concentration,
        "heatmap": heatmap,
        "top1": top1,
        "baselines": baselines,
        "team_rankings": team_rankings,
    }


def qa_checks(events: pd.DataFrame, bars: list[dict], conc: list[dict]) -> dict:
    shots = {"2FGA", "3FGA", "FTA", "2FGM", "3FGM", "FTM"}

    def row_sum(src, q, keep_set):
        rows = [b for b in bars
                if b["split"] == "all" and b["source"] == src and b["question"] == q
                and b["next_action"] in keep_set]
        return round(sum(b["p"] for b in rows), 3), rows

    def top_row(src, q):
        rows = [b for b in bars
                if b["split"] == "all" and b["source"] == src and b["question"] == q
                and b["rank"] == 0]
        return rows[0] if rows else None

    def conc_row(src, q, split="all"):
        for c in conc:
            if c["source"] == src and c["question"] == q and c["split"] == split:
                return c
        return None

    checks = {}

    p, _ = row_sum("3FGM", "q1", shots)
    checks["q1_after_3FGM"] = {
        "shot_share": p, "top1": top_row("3FGM", "q1"),
        "expect": "shot_share in [0.60, 0.75]"}

    defensive = {"CM", "D", "RV"}
    p, _ = row_sum("ST", "q1", defensive)
    checks["q1_after_ST"] = {
        "defensive_share": p, "top1": top_row("ST", "q1"),
        "expect": "defensive_share > 0.50"}

    p, _ = row_sum("2FGM", "q2", shots)
    c = conc_row("2FGM", "q2")
    checks["q2_after_2FGM"] = {
        "shot_share": p, "top1": top_row("2FGM", "q2"),
        "ppp_mean": c.get("ppp_mean") if c else None,
        "expect": "shot_share > 0.85, ppp in [0.8, 1.2]"}

    p, _ = row_sum("2FGA", "q2", shots)
    c = conc_row("2FGA", "q2")
    checks["q2_after_2FGA"] = {
        "shot_share": p, "top1": top_row("2FGA", "q2"),
        "ppp_mean": c.get("ppp_mean") if c else None,
        "expect": "shot_share > 0.80, ppp in [0.9, 1.3]"}

    checks["q0_after_2FGM"] = {
        "top1": top_row("2FGM", "q0"),
        "expect": "top1 == AS, p in [0.40, 0.55]"}

    # lift sanity
    top_q2_3fgm = top_row("3FGM", "q2")
    checks["q2_after_3FGM_lift_sanity"] = {
        "top1": top_q2_3fgm,
        "expect": "lift should be near 1.0 (same-team offensive baseline)"}

    return checks


# %% entry

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bootstrap", type=int, default=BOOTSTRAP)
    ap.add_argument("--fast", action="store_true",
                    help="Skip bootstrap CIs (faster smoke)")
    args = ap.parse_args()

    if args.fast:
        globals()["BOOTSTRAP"] = 0

    events = load_events()
    results = build_transitions(events)

    out = config.REPORTS_DIR
    out.mkdir(parents=True, exist_ok=True)

    (out / "transitions_bars.json").write_text(json.dumps({
        "n_games": int(events.groupby(["season", "game_id"]).ngroups),
        "n_events": int(len(events)),
        "seasons": sorted(int(s) for s in events["season"].unique()),
        "plain_labels": PLAIN_LABELS,
        "source_categories": SOURCE_CATEGORIES,
        "paired_sources": PAIRED_SOURCES,
        "bars": results["bars"],
    }, indent=2))
    (out / "transitions_concentration.json").write_text(
        json.dumps(results["concentration"], indent=2))
    (out / "transitions_heatmap.json").write_text(
        json.dumps(results["heatmap"], indent=2))
    (out / "transitions_team_rank.json").write_text(
        json.dumps(results["team_rankings"], indent=2))
    pd.DataFrame(results["top1"]).to_csv(out / "transitions_top1.csv", index=False)

    qa = qa_checks(events, results["bars"], results["concentration"])
    (out / "transitions_qa.json").write_text(json.dumps(qa, indent=2))

    log.info("wrote %d bar rows, %d concentration rows, %d heatmap cells, %d team rankings",
             len(results["bars"]), len(results["concentration"]),
             len(results["heatmap"]), len(results["team_rankings"]))
    log.info("QA checks:\n%s", json.dumps(qa, indent=2))


if __name__ == "__main__":
    main()
