# Plan: Replace Mock with Live Data + Add Mechanisms + EuroCup

**Created**: 2026-04-17
**Estimated total**: 7-8 hours of agent work + checkpoint pauses
**Goal**: Move the project from "fully built on synthetic data" to "fully measured on real data, with mechanism analysis and a measured cross-league benchmark."

---

## Guiding rules (per project policy)

1. **Sample-first, then full** -- every phase runs on a 1-season sample first, gets eyeballed, then runs full.
2. **Idempotent** -- every phase can be re-run safely. No appending to existing partitions.
3. **Resumable** -- ingestion checkpoints per (season, endpoint) so a failure mid-run doesn't lose progress.
4. **Provenance tagged** -- every row carries `data_source` so real and mock can never be confused.
5. **Checkpoint pauses** -- after each phase I post the headline numbers + 2-3 sanity-check rows; you eyeball; we proceed only on your "go".
6. **Stop on smell** -- if a number looks structurally off (e.g. HCA collapses to 0, or a season has 2x games), I stop and ask before continuing.
7. **Learning notes** -- every phase appends to `learning/technical-notes/` and `learning/debug-log.md` so the LLM-engineering side of the project keeps growing.

---

## Phase 1 -- Ingestion safety net (~30 min)

**Why first**: Live ingestion will hit rate limits, transient 5xx, and schema surprises. Hardening the client now prevents losing 2 hours later.

**Work**:
- Add `tenacity` retry/backoff to the API client (already imported, not used uniformly)
- Add a `requests.Session` with rate-limit headers, max 5 req/s
- Add per-(season, endpoint) checkpoint files under `data/lake/raw/_checkpoints/`
- Add a 30-game smoke test: pull `season=2024, gameNumber=1..30`, validate schema with pandera
- **DO NOT** touch the existing mock warehouse yet -- write to `data/lake/raw/live/` so we can compare side-by-side

**Deliverable**: 30 real games on disk, schema-validated, with the manifest tagged `source = "live"`.

**Checkpoint**: I post the 30 raw rows (margins, attendance, gameCode); you confirm 3-5 of them look right against [euroleaguebasketball.net](https://www.euroleaguebasketball.net).

---

## Phase 2 -- Live ingest, sample season (~30 min)

**Why before full**: Validates the full per-season pipeline (games + venues + standings) on a known season we can sanity-check.

**Work**:
- Pull all of season 2024-25 live (~310 games + 18 teams + venues)
- Run bronze + silver + warehouse build on JUST 2024
- Compare to current mock 2024 row-by-row: any team-name mismatches? venue-capacity reconciliation issues?
- Reconcile `data/reference/venue_capacity.csv` against real team_ids -- log any unmapped teams
- **Idempotency test**: run the ingest twice, confirm warehouse counts identical (this is what caught the 2023 duplication bug last time)

**Deliverable**: A real 2024-25 season fully through silver, with venue reconciliation report.

**Checkpoint**: I post:
- Game count for 2024-25 (should be ~310, not 605)
- League HCA for 2024-25 alone (mock said ~+3 pts)
- Top-3 / bottom-3 teams by HCA
- Any unmapped venues or teams

You confirm the team list looks right and the HCA isn't wildly off.

---

## Phase 3 -- Live ingest, full 10 seasons (~2 h)

**Why now**: Sample-validated, ingestion is stable, idempotency proven.

**Work**:
- Pull all 10 seasons (2015-16 through 2024-25)
- Estimated ~3,100 games + box-score endpoints (Phase 4 only) at 5 req/s = ~10-15 min ingestion + retries
- Run full bronze + silver + warehouse rebuild on real data
- Re-run features (Elo, attendance_ratio, days_rest, is_playoff, COVID flags)
- Re-run hypothesis tests (paired t / Wilcoxon / permutation / Spearman / ANOVA / Holm)
- Re-run logistic regression + interactions + calibration
- Re-run RF + LightGBM + SHAP + ROC
- Re-run mixed-effects + Ridge-FE
- Re-run COVID DiD experiment
- Re-render the analyst dashboard

**Deliverable**: The same dashboard, same charts, but every number measured on real data. `is_mock: true` banner gone.

**Checkpoint**: I open the dashboard and post a side-by-side table:

| Metric | Mock value | Live value |
|---|---|---|
| League HCA (pts) | +3.01 | ?.?? |
| Home win rate | 63.0% | ??.?% |
| n games | 3106 | ???? |
| Top team | Olympiakos | ??? |
| Bottom team | Alba Berlin | ??? |
| COVID HCA loss (DiD) | -1.82 | ?.?? |
| Logistic is_home OR | ? | ? |

You eyeball: do these numbers make basketball sense? If yes, we proceed to mechanism analysis.

**Stop conditions**: I stop and ask before continuing if any of:
- League HCA outside [+1.0, +5.0] range
- Any season with game count > 1.3x or < 0.7x the median
- COVID DiD has wrong sign (HCA *increased* with empty arenas)
- Mixed-effects model fails to converge

---

## Phase 4 -- Box-score ingestion (~2 h)

**Why now**: Real games are in. Box-scores unlock the *mechanism* analysis (the most-cited basketball-HCA finding in the literature).

**Work**:
- Add `/games/{gameCode}/teams/{teamCode}/stats` endpoint to the client
- Sample-first: pull box scores for 2024-25 only (~310 games × 2 teams = 620 calls, ~3 min at 5 req/s + retries)
- Spot-validate 5 random games against the official site (FGM, 3PA, FTA, fouls)
- Full pull: all 10 seasons (~6,200 calls, ~25 min)
- Build `fact_game_team_stats` for real (currently empty shell): FGM, FGA, 3PM, 3PA, FTM, FTA, ORB, DRB, AST, STL, BLK, TOV, PF
- Compute **real possessions** per game using the standard formula: `0.5 * ((FGA + 0.4*FTA - 1.07*(ORB/(ORB+opp_DRB))*(FGA-FGM) + TOV) + (opp same))`
- Replace the "assumes pace=75" caveat in the dashboard with the real measured pace per season

**Deliverable**: `fact_game_team_stats` populated, real possessions in the warehouse, real per-100-poss numbers in the dashboard.

**Checkpoint**: I post:
- Avg pace (poss/team/game) per season -- should be in 70-78 range
- Home vs away shooting% gap, FT-attempt gap, foul gap (the 3 mechanism candidates)
- Per-100-poss HCA (no longer assumed)

You eyeball: does pace look right? Is there a directional FT/foul gap?

---

## Phase 5 -- Mechanism analysis + dashboard tab (~1 h)

**Why now**: We have the data; this is the analytical payoff.

**Work**:
- Compute home-vs-away splits per stat with bootstrap CIs:
  - eFG% gap, 3P% gap, FT% gap
  - FTA differential (per 100 poss)
  - Foul differential (per 100 poss)
  - TOV differential
  - ORB% gap
- Decomposition: regress home margin on these gaps with a single OLS, report each stat's contribution to the +X pts HCA
- Add a 7th dashboard tab: **"Mechanisms"**, with:
  - Bar chart of each gap with CIs (positive = home advantage)
  - Decomposition pie/bar showing which stat contributes most to the home edge
  - A plain-English narrative: "Of the +X pts home edge, ~Y comes from referee-driven free throws, ~Z from shooting better, ~W from fewer turnovers"
  - Comparison to Moskowitz & Wertheim's NBA finding (FT differential dominant)
- Remove "shooting splits" and "FT/foul differential" from the "What we don't have (yet)" gap card -- they're now answered

**Deliverable**: A new Mechanisms tab in the dashboard. The project moves from "we measured HCA" to "we explained HCA."

**Checkpoint**: I open the dashboard, post the decomposition; you review the analytical narrative.

---

## Phase 6 -- EuroCup as a measured sister league (~45 min)

**Why now**: Same client, free comparison, restores the cross-league context honestly.

**Work**:
- Pull EuroCup (`competition=U`) for the same 10 seasons -- same ingestion path
- Build a parallel `eurocup` schema in the warehouse
- Compute the same descriptive HCA + per-team + attendance dose-response
- Re-add a "For context" panel to the dashboard with TWO measured rows: EuroLeague + EuroCup, with matching CIs
- A short note on the dashboard: which league has bigger HCA, and a hypothesis why (smaller arenas? less travel? lower-stakes games?)

**Deliverable**: A real, measured cross-league comparison panel. The "For context" section is no longer a self-context table.

**Checkpoint**: I post the EuroCup vs EuroLeague comparison; you review.

---

## Phase 7 -- Final QA, writeup, learning capture (~30-45 min)

**Why last**: Locks in what we learned for future-you.

**Work**:
- Append to `reports/llm-log.md`: what the LLM helped with this round (debugging schema mismatches, decomposition formula, narrative writing)
- Append to `learning/technical-notes/`:
  - One file on rate-limit handling + checkpoint design
  - One file on venue/team reconciliation gotchas
  - One file on possession-formula derivation
- Append to `learning/architecture-decisions/`:
  - ADR on "why we used real possessions instead of pace=75"
  - ADR on "why EuroCup but not NBA in this round"
- Update `README.md` with a "Reproducing the live pipeline" section
- Final dashboard review pass: no leftover mock references, all CIs render, narrative reads cleanly
- Open dashboard in browser

**Deliverable**: Project is "publishable" in the sense that someone else could read the README, run the pipeline, and get the same numbers.

---

## What I'm explicitly NOT doing in this round

These are good additions but don't fit the time budget. Park for later:

- **NBA via `nba_api`** -- 6-8 h by itself. Separate project.
- **NCAA via KenPom / sports-reference** -- paid / brittle. Skip.
- **Hierarchical Bayesian model (PyMC)** -- learning exercise, doesn't change conclusions.
- **Cluster-robust SEs** -- widens CIs ~10-15%, doesn't flip any conclusion. 30 min add later.
- **Quarter-by-quarter HCA** -- requires play-by-play (separate endpoint, separate ingestion). Out of scope.
- **Travel / time-zone effects** -- needs venue geocoding + flight-distance estimation. Separate project.
- **Interactive filters in the dashboard** -- design pass, not analysis.

---

## Estimated total time

| Phase | Work | Estimate |
|---|---|---|
| 1 | Ingestion safety net + 30-game smoke | 30 min |
| 2 | Live sample season (2024-25) | 30 min |
| 3 | Live full 10 seasons + re-run all models | 2 h |
| 4 | Box-score ingestion | 2 h |
| 5 | Mechanism analysis + new tab | 1 h |
| 6 | EuroCup ingestion + comparison panel | 45 min |
| 7 | QA, writeup, learning capture | 45 min |
| **Total** | | **~7.5 h** |

Add 30-60 min for checkpoint pauses + rework on whatever surprises us. Comfortably within 8 hours.

---

## Stop conditions (any of these = pause and ask)

- API returns >5% errors after retry
- A season has game count outside [0.7x, 1.3x] of median
- League HCA on real data is outside [+1.0, +5.0] pts
- Any model fails to converge or returns NaN coefficients
- Dashboard render throws an error
- Pace from real possessions is outside [65, 85]
- Box-score values fail spot-check vs official site by >10%

---

## Approval

If this looks right, say "go phase 1" and I'll start with the ingestion safety net. If you want to adjust scope (e.g. skip EuroCup, add Bayesian model, change the stop conditions), call it out before phase 1 starts -- once we're in the live pipeline I'd rather not change scope mid-flight.
