# Possession Formula Derivation

We calculate possessions per game using the standard basketball analytics formula:
`0.5 * ((FGA + 0.4*FTA - 1.07*(ORB/(ORB+opp_DRB))*(FGA-FGM) + TOV) + (opp same))`

## Why this formula?
1. **0.4*FTA**: Estimates the number of possessions that end in free throws (accounting for "and-1s" and 3-shot fouls).
2. **1.07*(ORB/(ORB+opp_DRB))*(FGA-FGM)**: Estimates the number of missed shots that result in an offensive rebound, which extends the possession rather than ending it. The 1.07 multiplier accounts for team rebounds.
3. **Averaging**: We average the team's estimated possessions with the opponent's estimated possessions to get a more stable and accurate measure of the game's pace.
