"""Tests for Phase F referee-bias analysis.

Invariants:
  1. Every (season, game_id) has 1-4 referee rows (never 0, never 5+).
  2. All ref_codes are non-empty strings.
  3. Summary KPIs are consistent with the per-ref records.
  4. p-values are in [0, 1]; Holm-adjusted >= raw.
  5. If the verdict is "null_result", no Holm p-value is < 0.05.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
REF_PARQUET = ROOT / "data" / "E" / "silver" / "fact_game_referee.parquet"
REF_OUT = ROOT / "reports" / "referee_output.json"
FACT_GAME = ROOT / "data" / "E" / "silver" / "fact_game.parquet"


@pytest.fixture(scope="module")
def refs():
    return pd.read_parquet(REF_PARQUET)


@pytest.fixture(scope="module")
def output():
    return json.loads(REF_OUT.read_text())


def test_ref_slots_in_range(refs):
    """Every game has 1-4 referees; slot values are 1-4 only."""
    assert refs["slot"].between(1, 4).all()
    per_game = refs.groupby(["season", "game_id"]).size()
    assert per_game.between(1, 4).all(), \
        f"game with {per_game.min()}-{per_game.max()} refs found"


def test_ref_codes_nonempty(refs):
    """No empty ref_codes."""
    assert (refs["ref_code"].str.len() > 0).all()
    assert refs["ref_code"].notna().all()


def test_every_game_has_refs(refs):
    """Every non-neutral game in fact_game should have referees assigned."""
    fg = pd.read_parquet(FACT_GAME)
    fg = fg[~fg["is_neutral"].fillna(False)]
    game_keys = set(zip(fg["season"], fg["game_id"]))
    ref_keys = set(zip(refs["season"], refs["game_id"]))
    missing = game_keys - ref_keys
    # Allow a tiny tolerance (<1%) for games with incomplete raw JSON
    assert len(missing) < 0.01 * len(game_keys), \
        f"{len(missing)} games missing referees (> 1% threshold)"


def test_summary_kpi_consistency(output):
    """KPI counts match the per-ref array."""
    k = output["kpi"]
    per_ref = output["per_ref"]
    assert len(per_ref) == k["n_refs_eligible"]
    assert sum(1 for r in per_ref if r["p_pf"] < 0.05) == k["n_significant_raw_pf"]
    assert sum(1 for r in per_ref if r["p_holm_pf"] < 0.05) == k["n_significant_holm_pf"]


def test_pvals_in_range(output):
    """All p-values lie in [0, 1]; Holm-adjusted >= raw."""
    for r in output["per_ref"]:
        assert 0.0 <= r["p_pf"] <= 1.0
        assert 0.0 <= r["p_fta"] <= 1.0
        assert 0.0 <= r["p_holm_pf"] <= 1.0
        assert r["p_holm_pf"] >= r["p_pf"] - 1e-9, \
            f"Holm < raw for {r['ref_name']}: {r['p_holm_pf']} < {r['p_pf']}"


def test_verdict_consistent_with_holm(output):
    """If verdict == 'null_result', no Holm p-value should be < 0.05."""
    k = output["kpi"]
    if k["verdict"] == "null_result":
        assert k["n_significant_holm_pf"] == 0
        assert k["n_significant_holm_fta"] == 0
        for r in output["per_ref"]:
            assert r["p_holm_pf"] >= 0.05 or r["p_holm_fta"] < 1.0  # at least one was tested
