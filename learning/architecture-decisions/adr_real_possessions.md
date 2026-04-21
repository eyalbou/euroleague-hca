# ADR: Why we used real possessions instead of pace=75

## Context
In Phase 1, we assumed a constant pace of 75 possessions per team per game for EuroLeague, based on historical FIBA averages. This was used to convert the raw point differential into a per-100-possessions metric.

## Decision
We decided to compute the real number of possessions per game using the standard basketball analytics formula from the live boxscore data.

## Rationale
1. **Accuracy**: Pace varies across seasons, teams, and games. Using a constant 75 introduces noise and bias into the per-100-possessions metric.
2. **Mechanism Analysis**: To accurately decompose the Home Court Advantage (HCA) into its constituent mechanisms (e.g., eFG%, TOV%, ORB%), we need precise per-possession rates.
3. **Data Availability**: The live EuroLeague API provides all the necessary boxscore stats (FGA, FGM, FTA, ORB, DRB, TOV) to compute possessions accurately.
