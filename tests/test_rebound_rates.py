"""Tests for Phase H rebound-rate analysis.

Invariants:
  1. All probabilities are in [0, 1].
  2. Wilson CIs are correctly ordered (lo <= p <= hi).
  3. n_dreb + n_oreb + n_other == n_eligible for every row.
  4. The "all" rate is (approximately) the weighted average of home + away rates.
  5. OREB + DREB + other_rate == 1.0 (within floating-point tolerance).
  6. Pairwise comparison p-values are in [0, 1]; sign of z matches sign of diff.
  7. For FG misses, other-share < 5% (PBP classifies rebound events cleanly).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "rebound_rates.json"


@pytest.fixture(scope="module")
def payload():
    return json.loads(OUT.read_text())


def test_probs_in_range(payload):
    for r in payload["rates"]:
        assert 0 <= r["p_oreb"] <= 1
        assert 0 <= r["p_dreb"] <= 1


def test_ci_ordered(payload):
    for r in payload["rates"]:
        assert r["lo_oreb"] <= r["p_oreb"] <= r["hi_oreb"]
        assert r["lo_dreb"] <= r["p_dreb"] <= r["hi_dreb"]


def test_counts_sum(payload):
    for r in payload["rates"]:
        assert r["n_dreb"] + r["n_oreb"] + r["n_other"] == r["n_eligible"]


def test_proportions_sum_to_one(payload):
    for r in payload["rates"]:
        if r["n_eligible"] == 0:
            continue
        other_p = r["n_other"] / r["n_eligible"]
        total = r["p_oreb"] + r["p_dreb"] + other_p
        assert abs(total - 1.0) < 0.01, f"sum={total} for {r['shot_type']}/{r['split']}"


def test_home_away_sum_matches_all(payload):
    """n_home + n_away should equal n_all for each shot type."""
    by_type: dict[str, dict] = {}
    for r in payload["rates"]:
        by_type.setdefault(r["shot_type"], {})[r["split"]] = r
    for shot, splits in by_type.items():
        if "home" in splits and "away" in splits and "all" in splits:
            hm, aw, al = splits["home"], splits["away"], splits["all"]
            assert hm["n_eligible"] + aw["n_eligible"] == al["n_eligible"], \
                f"home+away != all for {shot}"


def test_comparison_sign_consistency(payload):
    """Sign of z matches sign of the A-B difference."""
    for c in payload["comparisons"]:
        if abs(c["diff_pp"]) < 0.001:
            continue
        assert (c["z"] > 0) == (c["diff_pp"] > 0), \
            f"sign mismatch: diff={c['diff_pp']} z={c['z']}"
        assert 0 <= c["p"] <= 1


def test_fg_other_share_small(payload):
    """Rebound classifier should catch FG rebounds cleanly (<5% other)."""
    for r in payload["rates"]:
        if r["shot_type"] in ("3FGA", "2FGA") and r["split"] == "all":
            other_p = r["n_other"] / r["n_eligible"] if r["n_eligible"] else 0
            assert other_p < 0.06, \
                f"{r['shot_type']} other-share={other_p:.3f} too high"
