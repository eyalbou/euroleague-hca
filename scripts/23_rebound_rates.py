"""Phase 23 -- rebound rates by shot-miss type (3PT / 2PT / terminal FT).

Answers: after a missed 3-pointer vs 2-pointer vs (terminal) free throw, what is
the probability of an offensive rebound vs a defensive rebound?

Key subtlety vs the generic q0 transitions bars: free throws come in sequences
(1-of-2, 2-of-2, ...). The raw "next event after any FTA" is usually another
FTA or FTM in the same trip -- not a rebound. Only the *terminal* FT in a trip
is rebound-eligible. We detect terminal FTs by looking at the ordered PBP and
flagging any FT whose next event is either (a) by a different player or (b) not
an FT (FTA/FTM).

Outputs:
  reports/rebound_rates.json  -- per (shot_type x split) rebound rates + Wilson CIs
  reports/rebound_rates_qa.json  -- invariants for tests
"""
from __future__ import annotations

import argparse
import json
import logging
from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd
from scipy import stats as sst

from euroleague_hca import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("23_rebound_rates")

SILVER = config.SILVER_DIR / "fact_game_event.parquet"
OUT = config.REPORTS_DIR / "rebound_rates.json"
QA_OUT = config.REPORTS_DIR / "rebound_rates_qa.json"

SHOT_MISS_CODES = ["3FGA", "2FGA", "FTA"]


@dataclass
class RateRow:
    shot_type: str
    split: str
    n_eligible: int
    n_dreb: int
    n_oreb: int
    n_other: int
    p_dreb: float
    p_oreb: float
    lo_dreb: float
    hi_dreb: float
    lo_oreb: float
    hi_oreb: float
    dreb_share_of_rebounded: float
    oreb_share_of_rebounded: float


def _wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval. More honest than normal-approx at boundaries."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    halfw = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - halfw), min(1.0, center + halfw))


def _load_pbp(sample: bool) -> pd.DataFrame:
    log.info("loading silver PBP from %s", SILVER)
    df = pd.read_parquet(SILVER)
    # Dedup: the silver writer occasionally emits the same event twice when a raw
    # JSON snapshot was re-ingested. Key on the smallest tuple that uniquely
    # identifies an event.
    before = len(df)
    df = df.drop_duplicates(
        subset=["season", "game_id", "period", "period_arr_idx",
                "action_type", "player_id", "marker_time"]
    )
    log.info("loaded %d rows, dedup -> %d rows", before, len(df))
    if sample:
        # keep 200 games for smoke runs
        keep = df[["season", "game_id"]].drop_duplicates().head(200)
        df = df.merge(keep, on=["season", "game_id"], how="inner")
        log.info("sample: down to %d rows across %d games", len(df), len(keep))
    # sort for the ordered next-event lookup
    df = df.sort_values(
        ["season", "game_id", "period", "period_arr_idx"]
    ).reset_index(drop=True)
    return df


def _flag_terminal_fts(df: pd.DataFrame) -> pd.Series:
    """Return a boolean mask: True where action_type is FTA/FTM AND this FT is
    the terminal attempt of its trip.

    Heuristic: within a game, walk the ordered event stream. An FT event is
    terminal if the NEXT event in the same game is not an FT (FTA or FTM) by the
    SAME shooter. Edge case: last event of the game -> terminal by default.
    """
    is_ft = df["action_type"].isin(["FTA", "FTM"])
    # shifted "next" within game
    next_game = df["game_id"].shift(-1)
    next_season = df["season"].shift(-1)
    next_action = df["action_type"].shift(-1)
    next_player = df["player_id"].shift(-1)
    same_game = (next_game == df["game_id"]) & (next_season == df["season"])
    next_is_ft = next_action.isin(["FTA", "FTM"]) & same_game
    next_same_shooter = (next_player == df["player_id"]) & same_game
    # "continues" = next event is an FT by same shooter in same game
    continues = next_is_ft & next_same_shooter
    terminal = is_ft & ~continues
    return terminal


def _classify_rebound(df: pd.DataFrame, lookahead: int = 3) -> pd.DataFrame:
    """For each row, look at the next `lookahead` events in the same game and
    classify the outcome of the (presumed) miss as:
      'D'      : defensive rebound encountered
      'O'      : offensive rebound encountered
      'other'  : neither within the window (possession-ending event w/o rebound)

    We use a window because a missed 2 sometimes has a block annotation ("AG" /
    "FV") before the rebound in the event stream. Walking the next 3 events
    captures the rebound reliably without false positives -- the next rebound
    after a miss is always the rebound of THAT miss, since a new possession
    cannot start without a rebound, TO, made shot, or period boundary, and
    none of those are D/O events themselves.
    """
    df = df.copy()
    n = len(df)
    # Vectorized: for k=1..lookahead, pull the k-th future row via shift(-k),
    # but only if it stays in the same (season, game_id).
    #   classif[i] = first D/O found; else 'other'
    classif = np.full(n, "other", dtype=object)
    found = np.zeros(n, dtype=bool)
    action = df["action_type"].to_numpy()
    game = df["game_id"].to_numpy()
    season = df["season"].to_numpy()
    for k in range(1, lookahead + 1):
        # future arrays shifted by k (padded with sentinels that won't match)
        fut_action = np.concatenate([action[k:], np.array([""] * k, dtype=object)])
        fut_game = np.concatenate([game[k:], np.full(k, -1)])
        fut_season = np.concatenate([season[k:], np.full(k, -1)])
        same = (fut_game == game) & (fut_season == season)
        is_d = same & (fut_action == "D") & ~found
        is_o = same & (fut_action == "O") & ~found
        classif[is_d] = "D"
        classif[is_o] = "O"
        found |= (is_d | is_o)
    df["rebound_outcome"] = classif
    return df


def _wilson_row(k_dreb: int, k_oreb: int, n: int) -> tuple[float, float, float, float, float, float]:
    p_d = k_dreb / n if n else 0.0
    p_o = k_oreb / n if n else 0.0
    lo_d, hi_d = _wilson(k_dreb, n)
    lo_o, hi_o = _wilson(k_oreb, n)
    return p_d, p_o, lo_d, hi_d, lo_o, hi_o


def _compute_for_slice(miss_rows: pd.DataFrame, shot_type: str, split: str) -> RateRow:
    n = len(miss_rows)
    if n == 0:
        return RateRow(shot_type=shot_type, split=split, n_eligible=0,
                       n_dreb=0, n_oreb=0, n_other=0,
                       p_dreb=0.0, p_oreb=0.0,
                       lo_dreb=0.0, hi_dreb=0.0, lo_oreb=0.0, hi_oreb=0.0,
                       dreb_share_of_rebounded=0.0, oreb_share_of_rebounded=0.0)
    n_d = int((miss_rows["rebound_outcome"] == "D").sum())
    n_o = int((miss_rows["rebound_outcome"] == "O").sum())
    n_other = n - n_d - n_o
    p_d, p_o, lo_d, hi_d, lo_o, hi_o = _wilson_row(n_d, n_o, n)
    reb = n_d + n_o
    dreb_share = n_d / reb if reb else 0.0
    oreb_share = n_o / reb if reb else 0.0
    return RateRow(shot_type=shot_type, split=split, n_eligible=n,
                   n_dreb=n_d, n_oreb=n_o, n_other=n_other,
                   p_dreb=round(p_d, 4), p_oreb=round(p_o, 4),
                   lo_dreb=round(lo_d, 4), hi_dreb=round(hi_d, 4),
                   lo_oreb=round(lo_o, 4), hi_oreb=round(hi_o, 4),
                   dreb_share_of_rebounded=round(dreb_share, 4),
                   oreb_share_of_rebounded=round(oreb_share, 4))


def _two_proportion_z(p1: float, n1: int, p2: float, n2: int) -> tuple[float, float]:
    """Pooled two-proportion z-test. Returns (z, two-sided p)."""
    if n1 == 0 or n2 == 0:
        return (0.0, 1.0)
    p_pool = (p1 * n1 + p2 * n2) / (n1 + n2)
    se = np.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
    if se == 0:
        return (0.0, 1.0)
    z = (p1 - p2) / se
    p = 2 * (1 - sst.norm.cdf(abs(z)))
    return (float(z), float(p))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true")
    args = ap.parse_args()

    df = _load_pbp(sample=args.sample)

    # terminal FT flag
    terminal = _flag_terminal_fts(df)
    df = df.assign(is_terminal_ft=terminal.values)

    # lookahead rebound classifier
    df = _classify_rebound(df, lookahead=3)

    # Rebound-eligible miss events:
    #   3FGA + 3FGAB (blocked 3), 2FGA + 2FGAB (blocked 2), terminal FTA
    mask_3 = df["action_type"].isin(["3FGA", "3FGAB"])
    mask_2 = df["action_type"].isin(["2FGA", "2FGAB"])
    mask_ft = (df["action_type"] == "FTA") & df["is_terminal_ft"]

    misses_all = pd.concat([
        df.loc[mask_3].assign(miss_type="3FGA"),
        df.loc[mask_2].assign(miss_type="2FGA"),
        df.loc[mask_ft].assign(miss_type="FTA_terminal"),
    ], ignore_index=True)
    log.info("rebound-eligible misses: 3FGA=%d, 2FGA=%d, FTA_terminal=%d",
             mask_3.sum(), mask_2.sum(), mask_ft.sum())

    # Splits: all, home (miss by home team), away (miss by away team)
    out_rows: list[RateRow] = []
    for miss_type in ["3FGA", "2FGA", "FTA_terminal"]:
        sub = misses_all[misses_all["miss_type"] == miss_type]
        # all
        out_rows.append(_compute_for_slice(sub, miss_type, "all"))
        # home / away based on is_home of the shooter
        out_rows.append(_compute_for_slice(sub[sub["is_home"] == True],
                                           miss_type, "home"))
        out_rows.append(_compute_for_slice(sub[sub["is_home"] == False],
                                           miss_type, "away"))

    # Pairwise OREB-rate comparisons across shot types (all-split)
    rate_by = {r.shot_type: r for r in out_rows if r.split == "all"}
    comparisons = []
    pairs = [("3FGA", "2FGA"), ("3FGA", "FTA_terminal"), ("2FGA", "FTA_terminal")]
    for a, b in pairs:
        ra = rate_by[a]; rb = rate_by[b]
        z, p = _two_proportion_z(ra.p_oreb, ra.n_eligible, rb.p_oreb, rb.n_eligible)
        diff = ra.p_oreb - rb.p_oreb
        comparisons.append({
            "a": a, "b": b,
            "oreb_rate_a": ra.p_oreb, "oreb_rate_b": rb.p_oreb,
            "diff_pp": round(diff * 100, 3),
            "z": round(z, 3), "p": round(p, 6),
            "n_a": ra.n_eligible, "n_b": rb.n_eligible,
        })

    # Persist
    payload = {
        "meta": {
            "n_games": int(df[["season", "game_id"]].drop_duplicates().shape[0]),
            "seasons": sorted(df["season"].unique().tolist()),
            "built_by": "scripts/23_rebound_rates.py",
            "sample": bool(args.sample),
        },
        "rates": [asdict(r) for r in out_rows],
        "comparisons": comparisons,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2))
    log.info("wrote %s (%d rate rows, %d comparisons)",
             OUT, len(out_rows), len(comparisons))

    # QA / invariants for tests
    qa = {
        "n_shot_types": len({r.shot_type for r in out_rows}),
        "n_splits": len({r.split for r in out_rows}),
        "total_eligible_all": sum(r.n_eligible for r in out_rows if r.split == "all"),
        "dreb_plus_oreb_le_n": all(r.n_dreb + r.n_oreb <= r.n_eligible for r in out_rows),
        "all_probs_in_0_1": all(0 <= r.p_dreb <= 1 and 0 <= r.p_oreb <= 1 for r in out_rows),
        "ci_ordered": all(r.lo_dreb <= r.p_dreb <= r.hi_dreb
                          and r.lo_oreb <= r.p_oreb <= r.hi_oreb for r in out_rows),
    }
    QA_OUT.write_text(json.dumps(qa, indent=2))
    log.info("wrote %s", QA_OUT)


if __name__ == "__main__":
    main()
