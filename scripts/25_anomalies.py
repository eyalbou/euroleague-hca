"""Phase 25 -- ten basketball and data anomalies.

Each section computes one self-contained finding. All are written to a single
JSON output so the dashboard can render them without recomputation.

Anomalies:
  1. Overtime HCA -- does home advantage survive regulation ending tied?
  2. First-score effect -- who scores first and who wins
  3. Quarter-by-quarter HCA -- which quarter drives the league-wide +3.88
  4. Clutch HCA -- home win rate in games decided by <= 5
  5. Blowout asymmetry -- 20+ point wins at home vs on the road
  6. Halftime comeback rate -- trailing 10+ at half, win % (home vs away)
  7. Tied-at-half HCA -- when the game is a coin flip at halftime, who wins?
  8. Team 3PT home-road shooting gap -- biggest travel penalties
  9. FT% home-vs-away myth -- does the crowd actually affect FT shooting?
 10. Player scoring splits -- biggest home-warrior / road-warrior differentials
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd
from scipy import stats as sst

from euroleague_hca import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("25_anomalies")

SILVER = config.SILVER_DIR
OUT = config.REPORTS_DIR / "anomalies.json"


def _wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    halfw = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - halfw), min(1.0, center + halfw))


def _mean_ci(arr: np.ndarray, n_boot: int = 1000, seed: int = 20260421) -> tuple[float, float, float]:
    """Bootstrap 95% CI on the mean."""
    if len(arr) == 0:
        return (0.0, 0.0, 0.0)
    rng = np.random.default_rng(seed)
    boots = np.array([rng.choice(arr, size=len(arr), replace=True).mean()
                      for _ in range(n_boot)])
    return (float(arr.mean()), float(np.percentile(boots, 2.5)),
            float(np.percentile(boots, 97.5)))


# ============================================================================
# Anomaly 1 -- OVERTIME HCA
# ============================================================================
def anomaly_overtime_hca(games: pd.DataFrame) -> dict:
    reg = games[~games["overtime"]]
    ot = games[games["overtime"]]
    reg_win = int(reg["home_win"].sum())
    reg_n = len(reg)
    ot_win = int(ot["home_win"].sum())
    ot_n = len(ot)
    reg_p = reg_win / reg_n
    ot_p = ot_win / ot_n
    lo_r, hi_r = _wilson(reg_win, reg_n)
    lo_o, hi_o = _wilson(ot_win, ot_n)
    # two-proportion z
    p_pool = (reg_win + ot_win) / (reg_n + ot_n)
    se = np.sqrt(p_pool * (1 - p_pool) * (1 / reg_n + 1 / ot_n))
    z = (reg_p - ot_p) / se if se > 0 else 0.0
    p_val = 2 * (1 - sst.norm.cdf(abs(z)))
    return {
        "id": "overtime_hca",
        "title": "The OT coin flip",
        "regulation": {"n": reg_n, "home_win_p": round(reg_p, 4),
                       "lo": round(lo_r, 4), "hi": round(hi_r, 4)},
        "overtime": {"n": ot_n, "home_win_p": round(ot_p, 4),
                     "lo": round(lo_o, 4), "hi": round(hi_o, 4)},
        "diff_pp": round((reg_p - ot_p) * 100, 2),
        "z": round(float(z), 3),
        "p_value": round(float(p_val), 4),
    }


# ============================================================================
# Anomaly 2 -- FIRST-SCORE EFFECT
# ============================================================================
def anomaly_first_score(pbp: pd.DataFrame, games: pd.DataFrame) -> dict:
    """For each game, find the first team to score, cross-reference with the
    winner. Does scoring first predict winning?
    """
    scoring = pbp[pbp["action_type"].isin(["2FGM", "3FGM", "FTM"])].copy()
    # first scoring event per (season, game_id)
    first = scoring.sort_values(["season", "game_id", "period", "period_arr_idx"]).groupby(
        ["season", "game_id"], as_index=False).first()
    first = first[["season", "game_id", "is_home"]].rename(columns={"is_home": "first_score_home"})
    m = games.merge(first, on=["season", "game_id"], how="inner")
    # P(home wins | home scored first)
    sh = m[m["first_score_home"] == True]  # noqa: E712
    sa = m[m["first_score_home"] == False]  # noqa: E712
    p_h = sh["home_win"].mean()
    p_a = sa["home_win"].mean()  # home wins when AWAY scored first (i.e., home came back)
    lo_h, hi_h = _wilson(int(sh["home_win"].sum()), len(sh))
    lo_a, hi_a = _wilson(int(sa["home_win"].sum()), len(sa))
    # "scored-first team wins" rate across all games
    m["first_score_won"] = np.where(
        m["first_score_home"] == True,
        m["home_win"] == 1,
        m["home_win"] == 0,
    )
    first_won_p = m["first_score_won"].mean()
    lo_fw, hi_fw = _wilson(int(m["first_score_won"].sum()), len(m))
    return {
        "id": "first_score",
        "title": "Does scoring first predict winning?",
        "n_games": len(m),
        "home_scored_first": {"n": len(sh), "home_win_p": round(float(p_h), 4),
                              "lo": round(lo_h, 4), "hi": round(hi_h, 4)},
        "away_scored_first": {"n": len(sa), "home_win_p": round(float(p_a), 4),
                              "lo": round(lo_a, 4), "hi": round(hi_a, 4)},
        "scored_first_team_wins": {"p": round(float(first_won_p), 4),
                                   "lo": round(lo_fw, 4), "hi": round(hi_fw, 4)},
    }


# ============================================================================
# Anomaly 3 -- QUARTER-BY-QUARTER HCA
# ============================================================================
def anomaly_quarter_hca(pbp: pd.DataFrame) -> dict:
    """Per-game home-minus-away margin by quarter (points_home / points_away
    are running totals in PBP -- diff the end of each quarter from the end of
    the previous quarter).
    """
    # Keep only regulation periods (1..4). OT quarters are small sample + noisy.
    regp = pbp[pbp["period"].isin([1, 2, 3, 4])]
    # End of each period: last event in that period per game
    end = regp.sort_values(["season", "game_id", "period", "period_arr_idx"]).groupby(
        ["season", "game_id", "period"], as_index=False).last()[
            ["season", "game_id", "period", "points_home", "points_away"]]
    end = end.sort_values(["season", "game_id", "period"])
    # Shift within game to get prev-period cumulative score
    end["prev_home"] = end.groupby(["season", "game_id"])["points_home"].shift(1).fillna(0)
    end["prev_away"] = end.groupby(["season", "game_id"])["points_away"].shift(1).fillna(0)
    end["qtr_home_pts"] = end["points_home"] - end["prev_home"]
    end["qtr_away_pts"] = end["points_away"] - end["prev_away"]
    end["qtr_margin"] = end["qtr_home_pts"] - end["qtr_away_pts"]
    by_q = []
    for q in [1, 2, 3, 4]:
        sub = end[end["period"] == q]["qtr_margin"].to_numpy().astype(float)
        m, lo, hi = _mean_ci(sub, n_boot=500)
        by_q.append({"quarter": q, "n": len(sub),
                     "mean_home_margin": round(m, 4),
                     "lo": round(lo, 4), "hi": round(hi, 4),
                     "mean_home_pts": round(float(end[end["period"] == q]["qtr_home_pts"].mean()), 2),
                     "mean_away_pts": round(float(end[end["period"] == q]["qtr_away_pts"].mean()), 2)})
    return {
        "id": "quarter_hca",
        "title": "Which quarter produces the league-wide HCA?",
        "by_quarter": by_q,
        "sum_margin": round(sum(q["mean_home_margin"] for q in by_q), 3),
    }


# ============================================================================
# Anomaly 4 -- CLUTCH HCA
# ============================================================================
def anomaly_clutch_hca(games: pd.DataFrame) -> dict:
    """HCA in games decided by <=5, <=10, >10."""
    out = []
    for label, mask in [
        ("close (<=5)", games["home_margin"].abs() <= 5),
        ("medium (6-10)", (games["home_margin"].abs() > 5) & (games["home_margin"].abs() <= 10)),
        ("blowout (>10)", games["home_margin"].abs() > 10),
    ]:
        sub = games[mask]
        wins = int(sub["home_win"].sum())
        n = len(sub)
        p = wins / n if n else 0.0
        lo, hi = _wilson(wins, n)
        out.append({"bucket": label, "n": n, "home_win_p": round(p, 4),
                    "lo": round(lo, 4), "hi": round(hi, 4)})
    return {
        "id": "clutch_hca",
        "title": "Does HCA survive close games?",
        "buckets": out,
    }


# ============================================================================
# Anomaly 5 -- BLOWOUT ASYMMETRY
# ============================================================================
def anomaly_blowout_asymmetry(games: pd.DataFrame) -> dict:
    """20+ point wins at home vs away."""
    home_blowouts = int((games["home_margin"] >= 20).sum())
    away_blowouts = int((games["home_margin"] <= -20).sum())
    n = len(games)
    lo_h, hi_h = _wilson(home_blowouts, n)
    lo_a, hi_a = _wilson(away_blowouts, n)
    # 10+ variant
    home_10 = int((games["home_margin"] >= 10).sum())
    away_10 = int((games["home_margin"] <= -10).sum())
    # 30+ variant
    home_30 = int((games["home_margin"] >= 30).sum())
    away_30 = int((games["home_margin"] <= -30).sum())
    return {
        "id": "blowout_asymmetry",
        "title": "Home blowouts vs road blowouts",
        "n_games": n,
        "thresholds": [
            {"margin": 10, "home": home_10, "away": away_10,
             "home_p": round(home_10 / n, 4), "away_p": round(away_10 / n, 4),
             "ratio": round(home_10 / max(1, away_10), 2)},
            {"margin": 20, "home": home_blowouts, "away": away_blowouts,
             "home_p": round(home_blowouts / n, 4), "away_p": round(away_blowouts / n, 4),
             "ratio": round(home_blowouts / max(1, away_blowouts), 2),
             "home_lo": round(lo_h, 4), "home_hi": round(hi_h, 4),
             "away_lo": round(lo_a, 4), "away_hi": round(hi_a, 4)},
            {"margin": 30, "home": home_30, "away": away_30,
             "home_p": round(home_30 / n, 4), "away_p": round(away_30 / n, 4),
             "ratio": round(home_30 / max(1, away_30), 2)},
        ],
    }


# ============================================================================
# Anomaly 6 -- HALFTIME COMEBACK RATE
# ============================================================================
def anomaly_halftime_comeback(pbp: pd.DataFrame, games: pd.DataFrame) -> dict:
    """Score at end of Q2. Trailing by 10+ at half -> win %."""
    p2 = pbp[pbp["period"] == 2]
    end_q2 = p2.sort_values(["season", "game_id", "period_arr_idx"]).groupby(
        ["season", "game_id"], as_index=False).last()[
            ["season", "game_id", "points_home", "points_away"]]
    end_q2 = end_q2.rename(columns={"points_home": "q2_home", "points_away": "q2_away"})
    end_q2["q2_margin"] = end_q2["q2_home"] - end_q2["q2_away"]
    m = games.merge(end_q2, on=["season", "game_id"], how="inner")
    # Home trails by >= 10 at half
    home_down = m[m["q2_margin"] <= -10]
    home_cb = int(home_down["home_win"].sum())
    # Away trails by >= 10 at half (i.e., home leads by 10+)
    away_down = m[m["q2_margin"] >= 10]
    away_cb = int((away_down["home_win"] == 0).sum())
    return {
        "id": "halftime_comeback",
        "title": "The 10-point halftime hole",
        "home_trailing": {
            "n": len(home_down),
            "comeback_p": round(home_cb / max(1, len(home_down)), 4),
            "lo": round(_wilson(home_cb, len(home_down))[0], 4),
            "hi": round(_wilson(home_cb, len(home_down))[1], 4),
        },
        "away_trailing": {
            "n": len(away_down),
            "comeback_p": round(away_cb / max(1, len(away_down)), 4),
            "lo": round(_wilson(away_cb, len(away_down))[0], 4),
            "hi": round(_wilson(away_cb, len(away_down))[1], 4),
        },
    }


# ============================================================================
# Anomaly 7 -- TIED-AT-HALF HCA
# ============================================================================
def anomaly_tied_at_half(pbp: pd.DataFrame, games: pd.DataFrame) -> dict:
    p2 = pbp[pbp["period"] == 2]
    end_q2 = p2.sort_values(["season", "game_id", "period_arr_idx"]).groupby(
        ["season", "game_id"], as_index=False).last()[
            ["season", "game_id", "points_home", "points_away"]]
    end_q2["q2_margin"] = end_q2["points_home"] - end_q2["points_away"]
    m = games.merge(end_q2, on=["season", "game_id"], how="inner")
    # Tied at half (exact)
    tied = m[m["q2_margin"] == 0]
    close_half = m[m["q2_margin"].abs() <= 2]
    for label, df in [("tied_exact", tied), ("within_2", close_half)]:
        wins = int(df["home_win"].sum())
        n = len(df)
    # Full results
    res = {}
    for label, df in [("tied_exact", tied), ("within_2", close_half)]:
        wins = int(df["home_win"].sum())
        n = len(df)
        lo, hi = _wilson(wins, n)
        res[label] = {"n": n, "home_win_p": round(wins / max(1, n), 4),
                      "lo": round(lo, 4), "hi": round(hi, 4)}
    return {
        "id": "tied_at_half",
        "title": "Tied at halftime -- pure HCA",
        "buckets": res,
    }


# ============================================================================
# Anomaly 8 -- TEAM 3PT HOME/ROAD GAPS
# ============================================================================
def anomaly_team_3pt_gap(stats: pd.DataFrame) -> dict:
    """Per-team home vs away 3PT% gap, with a minimum sample size."""
    # Aggregate per team, per is_home
    g = stats.groupby(["team_id", "is_home"]).agg(
        fga3=("fga3", "sum"), fgm3=("fgm3", "sum"), games=("game_id", "count")
    ).reset_index()
    g["fg3_pct"] = g["fgm3"] / g["fga3"].where(g["fga3"] > 0, np.nan)
    home = g[g["is_home"] == 1].set_index("team_id")
    away = g[g["is_home"] == 0].set_index("team_id")
    both = home.join(away, lsuffix="_h", rsuffix="_a", how="inner")
    # Require at least 50 home + 50 away games
    both = both[(both["games_h"] >= 50) & (both["games_a"] >= 50)]
    both["gap_pp"] = (both["fg3_pct_h"] - both["fg3_pct_a"]) * 100
    both["n_3fga"] = both["fga3_h"] + both["fga3_a"]
    # Top 5 home-shooters (positive gap) and road-warriors (negative gap)
    top_home = both.sort_values("gap_pp", ascending=False).head(5)
    top_road = both.sort_values("gap_pp").head(5)
    def _rows(df):
        return [
            {"team_id": tid, "fg3_pct_home": round(r["fg3_pct_h"] * 100, 2),
             "fg3_pct_away": round(r["fg3_pct_a"] * 100, 2),
             "gap_pp": round(r["gap_pp"], 2),
             "n_home_games": int(r["games_h"]), "n_away_games": int(r["games_a"])}
            for tid, r in df.iterrows()
        ]
    return {
        "id": "team_3pt_gap",
        "title": "Which teams travel worst with their 3-point shot?",
        "top_home_shooters": _rows(top_home),
        "top_road_warriors": _rows(top_road),
        "n_teams": len(both),
        "league_mean_gap_pp": round(float(both["gap_pp"].mean()), 3),
    }


# ============================================================================
# Anomaly 9 -- FT% HOME/AWAY MYTH
# ============================================================================
def anomaly_ft_myth(stats: pd.DataFrame) -> dict:
    """Is FT% different at home vs away? Classic NBA myth: crowd distracts
    the visiting shooter. Test it in EuroLeague."""
    home = stats[stats["is_home"] == 1]
    away = stats[stats["is_home"] == 0]
    home_ft_pct = home["ftm"].sum() / home["fta"].sum()
    away_ft_pct = away["ftm"].sum() / away["fta"].sum()
    diff_pp = (home_ft_pct - away_ft_pct) * 100
    # two-proportion z
    nh, na = int(home["fta"].sum()), int(away["fta"].sum())
    kh, ka = int(home["ftm"].sum()), int(away["ftm"].sum())
    p_pool = (kh + ka) / (nh + na)
    se = np.sqrt(p_pool * (1 - p_pool) * (1 / nh + 1 / na))
    z = (home_ft_pct - away_ft_pct) / se
    p_val = 2 * (1 - sst.norm.cdf(abs(z)))
    return {
        "id": "ft_myth",
        "title": "Does the crowd actually rattle FT shooters?",
        "home": {"ftm": kh, "fta": nh, "ft_pct": round(float(home_ft_pct) * 100, 3)},
        "away": {"ftm": ka, "fta": na, "ft_pct": round(float(away_ft_pct) * 100, 3)},
        "diff_pp": round(float(diff_pp), 3),
        "z": round(float(z), 3),
        "p_value": round(float(p_val), 4),
    }


# ============================================================================
# Anomaly 10 -- PLAYER SCORING SPLITS (home vs road)
# ============================================================================
def anomaly_player_splits(pbp: pd.DataFrame) -> dict:
    """Per-player home/road PPG. Biggest differentials (home warriors and road warriors)."""
    scoring_map = {"2FGM": 2, "3FGM": 3, "FTM": 1}
    sc = pbp[pbp["action_type"].isin(scoring_map.keys())].copy()
    sc["pts"] = sc["action_type"].map(scoring_map)
    # per (player, game, is_home)
    per_game = sc.groupby(["player_id", "player_name", "season", "game_id", "is_home"], as_index=False).agg(
        pts=("pts", "sum"))
    # per (player, is_home) -- games and total points
    agg = per_game.groupby(["player_id", "player_name", "is_home"]).agg(
        pts_total=("pts", "sum"), games=("game_id", "count")
    ).reset_index()
    agg["ppg"] = agg["pts_total"] / agg["games"]
    home = agg[agg["is_home"] == 1].set_index("player_id")
    away = agg[agg["is_home"] == 0].set_index("player_id")
    both = home.join(away, lsuffix="_h", rsuffix="_a", how="inner")
    # Require 50+ games each side (real sample)
    both = both[(both["games_h"] >= 50) & (both["games_a"] >= 50)]
    both["diff_ppg"] = both["ppg_h"] - both["ppg_a"]
    both["total_games"] = both["games_h"] + both["games_a"]
    top_home = both.sort_values("diff_ppg", ascending=False).head(5)
    top_road = both.sort_values("diff_ppg").head(5)
    def _rows(df):
        return [
            {"player_id": pid,
             "player_name": r["player_name_h"] if pd.notna(r.get("player_name_h")) else r.get("player_name_a"),
             "ppg_home": round(r["ppg_h"], 2), "ppg_away": round(r["ppg_a"], 2),
             "diff_ppg": round(r["diff_ppg"], 2),
             "games_home": int(r["games_h"]), "games_away": int(r["games_a"])}
            for pid, r in df.iterrows()
        ]
    return {
        "id": "player_splits",
        "title": "The biggest home warriors and road warriors",
        "n_players_eligible": len(both),
        "min_games_each_side": 50,
        "top_home_warriors": _rows(top_home),
        "top_road_warriors": _rows(top_road),
    }


# ============================================================================
# Main
# ============================================================================
def main() -> None:
    log.info("loading silver data...")
    games = pd.read_parquet(SILVER / "fact_game.parquet")
    games = games[~games["is_neutral"]]  # exclude neutral-site games for HCA analyses
    pbp = pd.read_parquet(SILVER / "fact_game_event.parquet")
    pbp = pbp.drop_duplicates(
        subset=["season", "game_id", "period", "period_arr_idx",
                "action_type", "player_id", "marker_time"])
    stats = pd.read_parquet(SILVER / "fact_game_team_stats.parquet")
    stats = stats[~stats["is_neutral"]]
    log.info("games=%d pbp=%d stats=%d", len(games), len(pbp), len(stats))

    anomalies = []
    log.info("1. overtime_hca")
    anomalies.append(anomaly_overtime_hca(games))
    log.info("2. first_score")
    anomalies.append(anomaly_first_score(pbp, games))
    log.info("3. quarter_hca")
    anomalies.append(anomaly_quarter_hca(pbp))
    log.info("4. clutch_hca")
    anomalies.append(anomaly_clutch_hca(games))
    log.info("5. blowout_asymmetry")
    anomalies.append(anomaly_blowout_asymmetry(games))
    log.info("6. halftime_comeback")
    anomalies.append(anomaly_halftime_comeback(pbp, games))
    log.info("7. tied_at_half")
    anomalies.append(anomaly_tied_at_half(pbp, games))
    log.info("8. team_3pt_gap")
    anomalies.append(anomaly_team_3pt_gap(stats))
    log.info("9. ft_myth")
    anomalies.append(anomaly_ft_myth(stats))
    log.info("10. player_splits")
    anomalies.append(anomaly_player_splits(pbp))

    payload = {
        "meta": {
            "n_games": int(len(games)),
            "seasons": sorted(games["season"].unique().tolist()),
            "built_by": "scripts/25_anomalies.py",
        },
        "anomalies": anomalies,
    }
    OUT.write_text(json.dumps(payload, indent=2))
    log.info("wrote %s (%.1f KB)", OUT, OUT.stat().st_size / 1024)


if __name__ == "__main__":
    main()
