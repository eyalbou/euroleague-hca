"""Invariants on the play-by-play + transitions outputs.

These are smoke tests that guard against regressions when re-running the
pipeline with new data. They read the committed JSONs from reports/ and
check structural + numerical invariants.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORTS = REPO_ROOT / "reports"


@pytest.fixture(scope="module")
def bars():
    p = REPORTS / "transitions_bars.json"
    assert p.exists(), f"missing {p} -- run scripts/12_transitions.py"
    return json.loads(p.read_text())


@pytest.fixture(scope="module")
def conc():
    p = REPORTS / "transitions_concentration.json"
    assert p.exists()
    return json.loads(p.read_text())


@pytest.fixture(scope="module")
def qa():
    p = REPORTS / "transitions_qa.json"
    assert p.exists()
    return json.loads(p.read_text())


@pytest.fixture(scope="module")
def hca():
    p = REPORTS / "hca_transitions.json"
    assert p.exists()
    return json.loads(p.read_text())


# 1. transitions_bars has the three Markov families and the expected splits.
def test_bars_questions_and_splits(bars):
    rows = bars["bars"]
    qs = {r["question"] for r in rows}
    sps = {r["split"] for r in rows}
    assert qs == {"q0", "q1", "q2"}, f"missing/extra questions: {qs}"
    assert {"all", "home_acting", "away_acting", "open_doors", "closed_doors"}.issubset(sps), sps


# 2. Probabilities in [0,1]; CIs enclose the point estimate for rank-0 (top-1)
# rows. The 'Other' bucket (rank=8) can have degenerate CIs so we only check
# the primary-ranked rows here.
def test_bars_probabilities_in_range(bars):
    for r in bars["bars"]:
        assert 0.0 <= r["p"] <= 1.0, r
        assert r["n"] >= 1, r
        if r["rank"] == 0 and r.get("lo") is not None and r.get("hi") is not None:
            # Allow a small slack -- bootstrap point estimate can drift marginally
            # outside percentile CIs for very spiky distributions.
            assert r["lo"] - 0.02 <= r["p"] <= r["hi"] + 0.02, r


# 3. Q2 top-1 response to a made 2 should be an offensive action.
def test_q2_offensive_dominance(bars):
    OFFENSIVE = {"2FGM", "2FGA", "3FGM", "3FGA", "FTM", "FTA", "TO", "OF"}
    q2 = [r for r in bars["bars"]
          if r["question"] == "q2" and r["split"] == "all" and r["rank"] == 0]
    assert q2, "no Q2 rank-0 rows found"
    # Critical: after a made 2-pointer, the next offensive action MUST be an offensive one
    # (this was the bug that required the OFFENSIVE_ACTIONS constant).
    for r in q2:
        if r["source"] in {"2FGM", "3FGM", "2FGA", "3FGA"}:
            assert r["next_action"] in OFFENSIVE, (
                f"Q2 top-1 after {r['source']} is {r['next_action']} -- expected offensive"
            )


# 4. QA structure is intact (known sanity keys exist).
def test_qa_has_expected_keys(qa):
    assert {"q1_after_3FGM", "q1_after_ST", "q2_after_2FGM", "q0_after_2FGM"}.issubset(qa)
    # Q2 after made 2: shot share > 0.85 (our refined definition)
    assert qa["q2_after_2FGM"]["shot_share"] >= 0.85, qa["q2_after_2FGM"]


# 5. Concentration metrics are finite and in expected ranges.
def test_concentration_sanity(conc):
    for r in conc:
        assert 0.0 <= r["gini"] <= 1.0, r
        assert r["entropy_bits"] >= 0.0, r
        if r.get("ppp_mean") is not None:
            assert -0.5 <= r["ppp_mean"] <= 3.0, r


# 6. HCA x transitions delta_ppp: every source has finite values and CIs enclose the mean.
def test_hca_delta_ppp_structure(hca):
    assert hca["per_source"], "no per_source data"
    for r in hca["per_source"]:
        assert r["delta_ppp"] is not None
        assert r["delta_lo"] <= r["delta_ppp"] + 1e-9 <= r["delta_hi"] + 1e-6, r
        assert r["n_home"] > 0 and r["n_away"] > 0


# 7. Headline numbers in HCA KPIs are plausible.
def test_hca_kpi_plausibility(hca):
    kpi = hca["kpi"]
    assert 0.02 <= kpi["weighted_delta_ppp"] <= 0.15, kpi
    assert 1.0 <= kpi["hca_from_possession_efficiency_pts"] <= 4.5, kpi
    # Every one of the 19 sources is positive (our key finding).
    assert kpi["pct_sources_positive_delta"] >= 0.9, kpi
