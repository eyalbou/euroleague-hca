"""Phase 12b -- second-order chains (bigrams) for the top sources.

For each of the top-6 source actions by volume, compute the most common
(next_q0, next_next_q0) pairs -- i.e. "storylines" of three consecutive
events. Bootstrap CIs at the game level; top-5 paths per source.

Output: reports/transitions_bigrams.json
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
log = logging.getLogger("12b_bigrams")


TOP_N_SOURCES = 6
TOP_K_PATHS = 5
MIN_N = 500
BOOTSTRAP = 200
SEED = 42


PLAIN_LABELS = {
    "3FGM": "Made 3-pointer",  "3FGA": "Missed 3-pointer",
    "2FGM": "Made 2-pointer",  "2FGA": "Missed 2-pointer",
    "FTM":  "Made free throw", "FTA":  "Missed free throw",
    "AS":   "Assist",          "TO":   "Turnover",
    "D":    "Defensive rebound", "O":  "Offensive rebound",
    "ST":   "Steal",           "FV":  "Block (defender)",
    "AG":   "Shot blocked",    "CM":  "Foul committed",
    "RV":   "Foul drawn",      "OF":  "Offensive foul",
    "CMU":  "Unsportsmanlike foul", "CMT": "Technical foul",
}


def load_events() -> pd.DataFrame:
    events = pd.read_parquet(config.SILVER_DIR / "fact_game_event.parquet")
    events = events[events["is_action"] == 1].copy()
    events = events.sort_values(["season", "game_id", "event_idx"]).reset_index(drop=True)
    log.info("loaded %d in-play events across %d games",
             len(events), events.groupby(["season", "game_id"]).ngroups)
    return events


def _add_next_next(events: pd.DataFrame) -> pd.DataFrame:
    """Add next_action_1 and next_action_2 (the two actions following the current one)."""
    out_parts = []
    for (_s, _gid), g in events.groupby(["season", "game_id"], sort=False):
        g = g.copy()
        g["next_1"] = g["action_type"].shift(-1)
        g["next_2"] = g["action_type"].shift(-2)
        out_parts.append(g)
    return pd.concat(out_parts, ignore_index=True)


def _top_sources(events: pd.DataFrame) -> list[str]:
    counts = events["action_type"].value_counts()
    # Skip 'Other' / admin-ish actions; require known label
    known = [a for a in counts.index if a in PLAIN_LABELS]
    return known[:TOP_N_SOURCES]


def _bigram_distribution(src_rows: pd.DataFrame) -> list[dict]:
    """Return top-K bigram paths with their share of all valid paths."""
    valid = src_rows.dropna(subset=["next_1", "next_2"])
    total = len(valid)
    if total == 0:
        return []
    pairs = Counter(zip(valid["next_1"], valid["next_2"]))
    top = pairs.most_common(TOP_K_PATHS)
    out = []
    for (a1, a2), cnt in top:
        out.append({
            "next_1": str(a1), "next_2": str(a2),
            "n": int(cnt), "p": round(cnt / total, 4),
        })
    return out


def _bootstrap_cis(src_rows: pd.DataFrame, paths: list[dict],
                   n_resamples: int = BOOTSTRAP, seed: int = SEED) -> list[dict]:
    """Cluster bootstrap at game level on the share of each path."""
    rng = np.random.default_rng(seed)
    games = src_rows.groupby(["season", "game_id"])
    game_keys = list(games.groups.keys())
    if len(game_keys) < 10:
        return paths

    # Pre-index per game
    per_game = {k: g[["next_1", "next_2"]].dropna() for k, g in games}
    target_pairs = [(p["next_1"], p["next_2"]) for p in paths]

    shares = {tp: [] for tp in target_pairs}
    for _ in range(n_resamples):
        idx = rng.integers(0, len(game_keys), size=len(game_keys))
        sampled_pairs = Counter()
        total = 0
        for i in idx:
            df = per_game[game_keys[i]]
            total += len(df)
            for a1, a2 in zip(df["next_1"], df["next_2"]):
                sampled_pairs[(a1, a2)] += 1
        if total == 0:
            continue
        for tp in target_pairs:
            shares[tp].append(sampled_pairs.get(tp, 0) / total)

    for p, tp in zip(paths, target_pairs):
        if shares[tp]:
            p["lo"] = round(float(np.quantile(shares[tp], 0.025)), 4)
            p["hi"] = round(float(np.quantile(shares[tp], 0.975)), 4)
    return paths


def main() -> None:
    events = load_events()
    log.info("adding next_1 and next_2 columns per game...")
    events = _add_next_next(events)

    sources = _top_sources(events)
    log.info("top sources: %s", sources)

    out = {
        "n_games": int(events.groupby(["season", "game_id"]).ngroups),
        "n_events": int(len(events)),
        "top_n_sources": TOP_N_SOURCES,
        "top_k_paths": TOP_K_PATHS,
        "plain_labels": PLAIN_LABELS,
        "bigrams": [],
    }

    for src in sources:
        src_rows = events[events["action_type"] == src]
        n_src = len(src_rows)
        if n_src < MIN_N:
            log.info("  skip %s (n=%d < %d)", src, n_src, MIN_N)
            continue
        paths = _bigram_distribution(src_rows)
        if paths:
            paths = _bootstrap_cis(src_rows, paths)
        coverage = sum(p["p"] for p in paths)
        out["bigrams"].append({
            "source": src,
            "source_label": PLAIN_LABELS.get(src, src),
            "n_source": int(n_src),
            "n_with_both_nexts": int(src_rows.dropna(subset=["next_1", "next_2"]).shape[0]),
            "top_k_coverage": round(coverage, 3),  # what fraction of 3-grams these top-K cover
            "paths": paths,
        })
        log.info("  %s: n=%d, top-%d coverage=%.3f, top-path='%s -> %s' p=%.3f",
                 src, n_src, TOP_K_PATHS, coverage,
                 paths[0]["next_1"], paths[0]["next_2"], paths[0]["p"])

    out_path = config.REPORTS_DIR / "transitions_bigrams.json"
    out_path.write_text(json.dumps(out, indent=2))
    log.info("wrote %s (%.0f KB)", out_path, out_path.stat().st_size / 1024)


if __name__ == "__main__":
    main()
