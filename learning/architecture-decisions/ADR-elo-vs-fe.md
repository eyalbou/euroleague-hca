# ADR -- Elo vs Team-Season Fixed Effects

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
| Elo + logistic                             | 0.6372   | 0.627    | 0.224 |
| Team-season FE (ridge logistic)            | 0.6551   | 0.638    | 0.231 |

## Decision
Elo is the default team-strength feature for downstream models. Rationale:

* Continuous and updates walk-forward within a season, so it reacts to early-season surprises
  without waiting for the season to end.
* Far lower-dimensional (4 features vs ~360 dummies for FE), so it
  generalizes better with our ~3,500-row training set.
* Near-equivalent held-out performance (within 0.018 log-loss).

## Consequence
We use Elo everywhere as the team-strength feature. Keep `07d_ridge_fe.py` as a reference
implementation; revisit if we add within-season signal (injuries, lineup changes) that Elo
can't track.
