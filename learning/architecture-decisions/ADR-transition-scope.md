# ADR -- Transition analysis scope

Status: **accepted** -- 2026-04-20

## Context

The user asked "after action X, what is the most likely next action?" A naive
answer is a single first-order Markov matrix over all events. That collapses
three distinct basketball questions into one noisy number dominated by
substitutions and clock events. We split them explicitly.

## Decision 1: Three matrices, not one

We compute three separate transition families per source action X:

| Question | Definition | What it answers |
|---|---|---|
| **Q0** | `LEAD(action)` over in-play events, no team filter | "What literally comes next in the event log?" -- mostly useful as context; dominated by SUB/foul events after made shots |
| **Q1** | First in-play event with `code_team != source.code_team` | "After team A does X, how does team B respond first?" -- the right question for defensive reactions |
| **Q2** | First OFFENSIVE event (`2FGA`, `3FGA`, `FTA`, `2FGM`, `3FGM`, `FTM`, `TO`, `OF`) by team A that is preceded by at least one team-B action between source and target | "When team A next has the ball on offense, what's their first attempt?" -- the right question for possession-level follow-through |

Rejected alternatives:

- Single "next action" matrix: conflates the above three and the top-1 becomes
  meaningless ("SUB" or "CM" wins for almost every source).
- Full possession_id labelling of every event (with canonical possession-end
  markers): we prototyped the logic but the event-targeting heuristic above
  (require intervening opposition events + restrict to offensive target set)
  gives the same top-1/top-5 answers at a fraction of the complexity.
  Verified on 2024-25: Q2 shot-share after `2FGM` = 86.4% (plan target: >85%);
  shot-share after `2FGA` = 85.3% (plan target: >80%). Both pass.

## Decision 2: First-order Markov, not higher-order

At EuroLeague volume (~1.5M events across 10 seasons) a second-order chain is
feasible but was ruled out because:

- With ~18 primary actions, a second-order matrix has 324 source rows. For
  meaningful 500-resample bootstrap CIs per row we need ~500+ events per source,
  which cuts the usable sources by ~60%.
- The user's question is phrased as "after X" (single-step conditioning).
- We can always layer n-grams later; the silver event table keeps all raw data.

## Decision 3: Cluster-bootstrap at the game level

Events within a game are not i.i.d. -- a team that shoots lots of 3s will over-
represent `3FGA`-as-source for multiple same-game events. We resample **games**
with replacement (not events) before computing per-source distributions. This
widens CIs by roughly 1.3-1.8x compared to event-level resampling, which is
realistic.

500 resamples per (source, question, split) -- stable to 3 decimal places at
this sample size.

## Decision 4: Don't collapse rebound direction

`D` (defensive) and `O` (offensive) rebounds are kept as separate source actions
and separate targets. They answer totally different questions (possession
change vs. same-team second chance); merging them hides the core possession-
flow question the user cares about.

## Decision 5: Target sets by question

- **Q0**: any in-play action (mostly SUB-dominated -- kept for context).
- **Q1**: any in-play action by the opponent (no restriction).
- **Q2**: only offensive-action target set {shots, FT, TO, OF}. Rebounds (D,
  O), steals (ST), fouls (CM, RV) by team A are *transition* events before the
  next offensive possession; we want the first *attempt* on that possession.

## Decision 6: Hide sources with n < 30 per split

Closed-doors split (n=251 games, mostly 2020-21) is thin for rare actions like
CMD (disqualifying foul, ~3 events total). We suppress any (source, question,
split) combination where n < 30 to avoid misleading bars with very wide CIs.

## Splits kept

`all`, `home_acting`, `away_acting`, `open_doors`, `closed_doors` -- five total.
Home / away split uses the source-event's `is_home` field. Closed-doors uses the
game-level `attendance == 0` flag (see tech note 05).

## Decision 7 (v2, 2026-04-20 evening pass): Lift vs baseline is the primary lens

The initial run exposed a degenerate pattern on Q2: after almost any basketball
event, the distribution of the team's next offensive attempt is *the league's
marginal shot mix* -- ~22% made 2, ~21% missed 2, ~16% missed 3, ~13% made 3,
~14% turnover, ~7% made FT, ~6% missed FT. The raw-P view made every Q2 panel
look identical.

The fix is to surface **lift = P(next | source) / P(next | any source, same split)**
as a toggleable bar value. A lift of 1.0 means "this source tells you nothing
beyond the league baseline"; a lift > 1 means the source raises the probability
of that next action. The color palette switches to diverging green/red around
lift = 1.

Concretely this lets us see:

- `Q2 | 2FGA | 2FGM` has raw P = 0.228 but **lift = 1.05**: missing a 2 barely
  nudges what you do next -- basketball has strong first-order memorylessness
  at the possession boundary.
- `Q0 | 2FGM | AS` has raw P = 0.45 and **lift = 5.06**: the assist-after-made-basket
  is the strongest lift in the whole dataset, and it's a pure logging artifact
  (the assist row is written right after the made shot).

Raw P is still the right default for answering "what literally happens most
often". Lift is the right default for "what does this source tell me that the
baseline doesn't".

## Decision 8 (v2): PPP on Q2 is the business metric

The ADR originally deferred PPP. After the first full-scale run we added it
back because without PPP, Q2 is just a transition pattern with no connection
to the game outcome. PPP is computed as:

- F = Q2 target event (first offensive action by A after opponent intervention)
- H = first team-B in-play event after F (end of A's possession)
- PPP = pts_A_ffilled[H-1] - pts_A_ffilled[F-1]

Sanity: PPP(Q2 after 2FGM) = 1.057; PPP(Q2 after 2FGA) = 1.086. Both land in
the league-wide 1.0-1.1 range expected for half-court possessions. The ~0.03
gap (favouring missed shots) reflects the expected-points advantage of a team
whose opponent had to rebound rather than inbound -- a small but real signal.

## Decision 9 (v2): Paired-event sources get a warning banner

The EuroLeague log double-books some physical events:

| Source | Paired partner | Meaning |
|---|---|---|
| `FV` (block, defender) | `AG` (shot blocked, shooter) | same physical block |
| `AG` | `FV` | same |
| `CM` (foul committed) | `RV` (foul drawn) | same physical foul |
| `RV` | `CM` | same |
| `OF` (offensive foul) | `CM` | opponent is logged as foul-committing defender |

For these sources Q1 will read ~0.80-0.95 dominated by the partner. This is
not a strategic finding, it's a data-logging convention. The dashboard shows
a yellow banner whenever one of these sources is selected, steering users to
the Q2 panel and the "Lift vs baseline" mode for basketball-meaningful answers.

## Decision 10 (v2): Per-team distinctiveness ranking

Added a new view that, for each source, ranks teams by the KL-divergence of
their Q2 distribution from the league baseline. Gives a scouting lens:
"after team X steals, their next possession is unusually heavy on 3-point
attempts relative to the league". Only teams with n >= 50 source events in
the full 10-season window appear.

Implementation: single pass over events, grouped by (source, code_team).
Output: `reports/transitions_team_rank.json`, ~240 KB for all sources.

## Deferred (still)

- **Higher-order chains** (bigrams of source actions): feasible, not yet needed.
- **Shot-location (x, y)**: requires the `/shots` endpoint, separate ingest.
- **Player-level chains**: requires a player-id dimension we haven't built.
- **Interactive time-horizon slider** (only show transitions happening within
  N seconds): data is computed (sec_q1/sec_q2 columns), UI not yet wired.
