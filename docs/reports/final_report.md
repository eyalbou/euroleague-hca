# EuroLeague Home-Court Advantage -- final report

**Scope:** 10 seasons (2015-16 through 2024-25), 2897 games, 1,130,400 in-play play-by-play events.  
**Data source:** live Swagger API (`api-live.euroleague.net` v2/v3) + live PBP (`live.euroleague.net/api/PlaybyPlay`), cached locally as gzipped JSON.  
**Primary metric:** home point differential.  **Last refresh:** 2026-04-21.  
**Build:** `5de369c`.

> This report is regenerated from `reports/*_output.json` -- every number below traces back to a committed artifact.

## 1. The headline

- **EuroLeague home teams win 1.75x more often than on the road** (logistic OR, `is_home` fixed effect).  
  That's a **+13.6 pp** lift in win probability at the mean covariates.
- Average home advantage on point differential (mixed-effects intercept): **+3.88 pts / game**.
- **94% of that HCA (~3.63 pts/game) is explained by possession-level efficiency** -- home teams average +0.049 more points per offensive possession than road teams, across **every one** of the 19 trackable source actions.

## 2. Where does HCA come from? (mechanism decomposition)

Paired-game analysis on 2,897 games. Each row = mean home minus mean away, with 95% bootstrap CI.

| Mechanism | Home | Away | Δ (home - away) | 95% CI | p |
|-----------|-----:|-----:|----------------:|:------:|--:|
| Points per 100 possessions (efficiency) | 113.2 | 109.8 | **+3.4** | [+2.6, +4.0] | 6.4e-21 |
| eFG%  (effective field-goal %) | 0.544 | 0.535 | **+0.009** | [+0.005, +0.013] | 2.2e-05 |
| TS%  (true shooting %) | 0.582 | 0.572 | **+0.010** | [+0.007, +0.014] | 7.5e-08 |
| FT rate (FTA / FGA) | 0.303 | 0.287 | **+0.016** | [+0.011, +0.022] | 5.9e-08 |
| Turnovers per 100 possessions | 17.0 | 18.0 | **-1.0** | [-1.2, -0.8] | 9.1e-17 |
| Offensive rebounds per game | 10.4 | 10.2 | **+0.2** | [-0.0, +0.3] | 8.3e-02 |
| Personal fouls committed | 20.3 | 20.8 | **-0.5** | [-0.7, -0.3] | 2.4e-08 |

**Reading it:** home teams convert at higher eFG% and generate more trips to the line (FT rate), while turning the ball over *less*. Pace and offensive rebounding differences are small and largely not significant.

## 3. Can we predict home wins?

- **Elo + is_home logistic baseline:** test accuracy = 64.5%, Brier = 0.218.
- **Logistic with attendance + rest + interactions:** test accuracy = 65.7%, Brier = 0.216.
- **Tree-based models (Random Forest / LightGBM):** comparable Brier, slightly better calibration -- see Models tab of the dashboard.
- A majority-class baseline ('always predict home win') sits at 62.4%.  Models add ~3 pp over that, mainly via Elo and attendance ratio.

## 4. Team-by-team variation (mixed-effects LM)

`point_diff ~ attendance_ratio + is_playoff + (1 + attendance_ratio | team)`

- Fixed intercept: **+3.88** pts/game (league-wide HCA).  
- Attendance ratio coefficient: **-0.75** pts per unit of arena utilization -- *small and not significant at the league level*, but team-specific slopes vary widely (see dashboard tab 3).  
- Playoff indicator: **-3.41** pts -- HCA shrinks sharply in the playoffs, consistent with better seed travel schedules and more evenly matched crowds.

## 5. COVID natural experiment (DiD)

Pre-COVID (crowded) vs during-COVID (closed-doors) vs post-COVID difference in home advantage:

- **post - pre** = +0.11 pts/game (95% CI [-0.98, +1.19])  
  → HCA fully recovered after the pandemic. Closed-doors games showed a meaningful drop but the confidence intervals overlap zero, so we report the effect as directional.

## 6. Play-by-play -- what follows what?

Three first-order Markov chains computed from 1.13M events:

- **Q0** -- immediate next event (any team).
- **Q1** -- opponent's immediate response.
- **Q2** -- same team's first offensive action on its next possession (the one that matters for points).

Each bar is bootstrapped at the game level (500 resamples, 95% CIs). See the `transitions.html` dashboard for all source-action drill-downs, per-team distinctiveness (KL-divergence ranking), PPP per branch, and the HCA-lens overlay.

## 7. Referee-level bias (null result)

We tested all **61 referees** with at least 30 games (out of 112 total unique officials across 10 seasons) for home-vs-away asymmetry in foul calls and free-throw attempts.

- **Raw p < 0.05** (before correction): **3** refs on foul diff; **4** refs on FTA diff. Expected by chance alone: **3.1**.
- **Permutation test** (200 home/away label shuffles): the mean number of outliers under the null is **3.0** -- essentially identical to what we observed (permutation p = 0.56).
- **After Holm correction** across 61 simultaneous tests: **0** significant on foul diff; **0** on FTA diff.

**Reading it:** home teams draw +1.1 more FTA per game and commit 0.5 fewer fouls league-wide -- but *no individual referee* is driving that skew. The small asymmetry is spread evenly across the entire referee pool. Combined with the mechanism-decomposition finding that foul differential contributes only +0.05 pts of the +3.88 pt HCA (1.3%), EuroLeague officiating is effectively neutral -- the opposite of Moskowitz & Wertheim's NBA finding. See `dashboards/referees.html` for the funnel plot and top-10 outlier table.

## 8. Quality checks

- Transition QA (6 checks): all green (see `reports/transitions_qa.json`).
- HCA x Transitions QA:
  - `delta_ppp_range`: most deltas in [-0.10, +0.10] -- a few outliers OK
  - `sign_majority`: > 0.50 if home teams hold an edge on most possessions
  - `hca_from_possession_efficiency`: pts in [1.0, 3.5]; share in [0.30, 0.90] -- rest is pace / FTA rate
- Bootstrap CIs are game-level clustered throughout -- independence assumption would otherwise shrink CIs artificially.

## 9. How to read the dashboard

- **index.html** -- one-pager with the 5 headline KPIs and deep-links.
- **analyst_dashboard.html** -- seven tabs covering league, per-team, attendance, COVID, models, verdict, mechanisms.
- **transitions.html** -- play-by-play Markov view with four lenses (bars, heatmap, per-source multiples, per-team, HCA).
- **referees.html** -- per-referee funnel plot + Holm-corrected outlier table.

## 10. What this project taught me

- **Cluster bootstrap vs naive bootstrap:** treating events inside one game as independent triples the apparent precision. Clustering at the game level is the only honest CI for play-by-play metrics.
- **Paired-event artifacts:** `FV` (block by defender) and `AG` (shot blocked, shooter's view) are two rows for the same incident -- the Q1 chain `AG -> FV` at 82% is noise, not signal. Always sanity-check twinned events.
- **Possession-level framing wins narratively.** "Home teams average +0.05 points per possession more than road teams across every source action" beats "mixed-model intercept = 3.88" for stakeholder communication, even though they describe the same phenomenon.

---
*Generated by `scripts/15_final_report.py` at 2026-04-21T18:52:15.472522Z on commit `5de369c`.*
