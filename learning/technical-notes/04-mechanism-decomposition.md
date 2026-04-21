# Phase 5 -- Mechanism decomposition: why HCA exists

Date: 2026-04-17
Phase: 5 (Box-scores + OLS decomposition of home margin)

## Goal

Phases 1-3 established *that* EuroLeague has a +3.78 pts / 62.4% home edge.
Phase 5 asks *why*: which basketball mechanisms (shooting, turnovers, fouls,
free-throws, rebounds) drive the gap?

## Method

For each game we compute the **home minus away differential** on six
stats: eFG%, FT rate (FTA/FGA), turnovers per 100 poss, offensive rebounds,
and personal fouls. We then regress the *home point differential* on these
five differentials via OLS.

The coefficient times the mean differential gives the *pts of HCA attributable
to that mechanism*; what the intercept captures is the residual home effect
not explained by measurable box-score gaps.

## Key data lessons

1. **Pivot key must include season.** `game_id` is an integer `gameCode`
   that repeats across seasons (range ~1-350). A `pivot_table(index="game_id", ...)`
   silently collapses 2,564 of 2,897 games to a single row per code. We now
   index by `["season", "game_id"]` everywhere we pivot home vs away. This
   was the single most subtle bug of the project.

2. **Target choice matters.** The boxscore API's `total.points` excludes
   overtime minutes; using it as OLS target drops ~2 pts of HCA. Using
   `team_pts` from the game summary (which matches the league HCA of +3.78)
   is the correct choice. The mechanism differentials stay from boxscore.

3. **Possession formula: single-team approximation.**
   `poss = fga + 0.44 * fta - oreb + tov`. This is Oliver/Kubatko's formula;
   the more accurate two-team average differs by <0.5 poss/game on our data.

## Findings (live data, 2897 games, 2015-2024)

| Mechanism          | pts of HCA attributed |
|--------------------|-----------------------|
| eFG%               | +0.69                 |
| TOV / 100 poss     | +0.42                 |
| FT rate (FTA/FGA)  | +0.14                 |
| OREB               | +0.11                 |
| PF differential    | +0.05                 |
| Intercept (unattr.)| +2.37                 |
| **Observed HCA**   | **+3.78**             |

Model R^2 = 0.921 on the margin (the stat differentials predict 92% of
game-to-game variance in margin, *conditional on a home baseline*).

## Interpretation

1. **Shooting efficiency is the single biggest measurable driver** (+0.69 pts,
   roughly 18% of HCA). Home teams shoot +1.7 eFG% points better, almost
   entirely because they take cleaner shots, not because they take more of them
   -- 2PT% edge +1.6pp, 3PT% edge +1.5pp.

2. **Ball security contributes +0.42 pts.** Home teams commit ~1 fewer TO
   per 100 possessions. This is sizable and statistically strong.

3. **Referee bias is small in Europe.** Home teams commit 0.5 fewer fouls
   and draw 0.5 more, but once the OLS controls for shooting and turnovers,
   the foul differential contributes only +0.05 pts of HCA. This is the
   opposite of Moskowitz & Wertheim's NBA finding in *Scorecasting*, where
   foul calls were the majority of NBA HCA. European refereeing appears
   much more neutral.

4. **The large +2.37 pt intercept is a puzzle.** It says ~63% of HCA is
   a generic "being at home" effect that isn't captured by any measurable
   in-game stat gap. Candidates: travel fatigue, sleep disruption, schedule
   compression, free-throw-line scoring under pressure, lineup / rotation
   changes that don't show up at the team aggregate. A follow-up study
   would need play-by-play data (to separate clutch vs non-clutch) or
   player-level tracking.

## What this means for the COVID puzzle

In Phase 3 we found the crowd contribution to HCA is not statistically
significant (95% CI crosses zero). This is consistent with our mechanism
finding here: if HCA is mostly driven by measurable basketball things
(shooting, TOV) plus a large residual, and very little by refereeing, then
removing the *crowd* -- which would primarily bias refs and tilt FT calls --
should have a modest effect, not a 3-pt one. Our data now explains both
observations coherently.
