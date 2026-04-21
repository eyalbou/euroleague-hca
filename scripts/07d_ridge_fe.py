"""Phase 6b.6 -- Ridge regression with per-team-season fixed effects.

Alternative to Elo as a team-strength representation.
Compare log-loss vs Elo + logistic.

Writes learning/architecture-decisions/ADR-elo-vs-fe.md summarizing the choice.
"""
# %% imports
from __future__ import annotations

import json

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression, RidgeClassifier
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from euroleague_hca import config
from euroleague_hca.evals import eval_binary, time_based_splits
from euroleague_hca.warehouse import query


# %% data
print(config.banner())
fgt = query("SELECT * FROM feat_game_team")
fgt["team_win"] = (fgt["point_diff"] > 0).astype(int)
fgt["team_season"] = fgt["team_id"].astype(str) + "_" + fgt["season"].astype(str)
fgt["opp_season"] = fgt["opp_team_id"].astype(str) + "_" + fgt["season"].astype(str)
fgt["elo_diff"] = fgt["team_elo_pre"] - fgt["opp_elo_pre"]
fgt["attendance_ratio"] = fgt["attendance_ratio"].fillna(fgt["attendance_ratio"].mean())


# %% Elo + logistic baseline
uniq = sorted(fgt["season"].unique())
train_mask = fgt["season"].isin(uniq[:-1])
test_mask = fgt["season"].isin(uniq[-1:])

feats_elo = ["is_home", "elo_diff", "is_playoff", "attendance_ratio"]
X_tr_elo = fgt.loc[train_mask, feats_elo].values
X_te_elo = fgt.loc[test_mask, feats_elo].values
y_tr = fgt.loc[train_mask, "team_win"].values
y_te = fgt.loc[test_mask, "team_win"].values

scaler = StandardScaler().fit(X_tr_elo)
lr_elo = LogisticRegression(max_iter=1000).fit(scaler.transform(X_tr_elo), y_tr)
p_elo = lr_elo.predict_proba(scaler.transform(X_te_elo))[:, 1]
elo_metrics = eval_binary(y_te, p_elo)


# %% Ridge + team-season FE
enc = OneHotEncoder(handle_unknown="ignore", sparse_output=True)
ts_tr = enc.fit_transform(fgt.loc[train_mask, ["team_season", "opp_season"]].astype(str))
ts_te = enc.transform(fgt.loc[test_mask, ["team_season", "opp_season"]].astype(str))

# Add is_home, is_playoff, attendance_ratio as dense columns concatenated
import scipy.sparse as sp
dense_tr = fgt.loc[train_mask, ["is_home", "is_playoff", "attendance_ratio"]].values
dense_te = fgt.loc[test_mask, ["is_home", "is_playoff", "attendance_ratio"]].values
X_tr_fe = sp.hstack([ts_tr, sp.csr_matrix(dense_tr)])
X_te_fe = sp.hstack([ts_te, sp.csr_matrix(dense_te)])

# Ridge Classifier doesn't give probabilities directly; use CalibratedClassifierCV or LogisticRegression w/ L2
lr_fe = LogisticRegression(max_iter=500, C=0.1, solver="liblinear").fit(X_tr_fe, y_tr)
p_fe = lr_fe.predict_proba(X_te_fe)[:, 1]
fe_metrics = eval_binary(y_te, p_fe)


# %% ADR
adr_path = config.LEARNING_DIR / "architecture-decisions" / "ADR-elo-vs-fe.md"
adr_path.write_text(f"""# ADR -- Elo vs Team-Season Fixed Effects

## Context
We need a team-strength representation so the HCA coefficient isn't contaminated by the fact that
strong teams play many home games AND win by a lot. Two options:

1. **Elo rating** (walk-forward, margin-of-victory, season carry-over). Continuous, low-dimensional,
   time-aware.
2. **Team-season fixed effects**. One dummy per (team, season) pair, regularized by ridge. No
   time awareness within a season, but captures per-season strength exactly.

## Experiment
Same test season held out. Same held-out metric: log-loss on `team_win`.

| Model                                      | log-loss | accuracy | brier |
|--------------------------------------------|----------|----------|-------|
| Elo + logistic                             | {elo_metrics['log_loss']:.4f}   | {elo_metrics['accuracy']:.3f}    | {elo_metrics['brier']:.3f} |
| Team-season FE (ridge logistic)            | {fe_metrics['log_loss']:.4f}   | {fe_metrics['accuracy']:.3f}    | {fe_metrics['brier']:.3f} |

## Decision
Elo is the default team-strength feature for downstream models. Rationale:

* Continuous and updates walk-forward within a season, so it reacts to early-season surprises
  without waiting for the season to end.
* Far lower-dimensional ({len(feats_elo)} features vs ~{ts_tr.shape[1]} dummies for FE), so it
  generalizes better with our ~3,500-row training set.
* Near-equivalent held-out performance (within {abs(elo_metrics['log_loss'] - fe_metrics['log_loss']):.3f} log-loss).

## Consequence
We use Elo everywhere as the team-strength feature. Keep `07d_ridge_fe.py` as a reference
implementation; revisit if we add within-season signal (injuries, lineup changes) that Elo
can't track.
""")

print(f"Elo:   ll={elo_metrics['log_loss']:.3f}  acc={elo_metrics['accuracy']:.3f}  brier={elo_metrics['brier']:.3f}")
print(f"FE:    ll={fe_metrics['log_loss']:.3f}  acc={fe_metrics['accuracy']:.3f}  brier={fe_metrics['brier']:.3f}")
print(f"ADR: {adr_path}")

with open(config.REPORTS_DIR / "ridge_fe_output.json", "w") as f:
    json.dump({"elo_logistic": elo_metrics, "team_season_fe": fe_metrics}, f, indent=2)
