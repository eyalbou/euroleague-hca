# Concepts learned -- statistics, ML, and data methods

Scope: one place to review every non-trivial method this project used, in the order I
encountered it, with a concrete example from our data and the intuition I want to
carry forward. Not a textbook -- a cheat sheet of things I would have gotten wrong on
day 1.

---

## 1. Paired-game analysis beats aggregate comparison

**Where it showed up:** mechanism decomposition (`scripts/11_mechanisms.py`).

**Wrong version:** compute league-wide mean eFG% at home vs away across all
team-games -- you get the right direction but inflated variance because team quality
confounds everything (good teams play more home games against weak opponents in any
given week).

**Right version:** for each game, take (home team's eFG% minus away team's eFG%), then
average those paired deltas across all 2,897 games. Team-quality drops out by
construction because both numbers are from the same game. The CI tightens by ~2-3x.

**Takeaway:** whenever two conditions are observed *within the same unit* (game,
player, patient), pair them. Independent-sample tests are wasteful and mildly
dishonest.

---

## 2. Cluster bootstrap for dependent observations

**Where it showed up:** every transition bar, every PPP delta, every storyline in the
PBP analysis.

**Problem:** events inside one game are not independent. Two shots by the same team in
the same 10 minutes share possession context, lineup, fatigue, refs. Treating them as
iid triples the apparent precision of any per-event average.

**Fix:** sample *games* with replacement (not events), then recompute the statistic on
the resampled corpus, repeat 500x. This is what every 95% CI in the transitions
dashboard does (`_bootstrap_cis` in `12_transitions.py` and `12b_bigrams.py`).

**Intuition:** ask "what happens if I replay the season 500 times?" not "what happens
if I reshuffle 1.13M events?". Events are not the unit of independence; games are.

**Cost:** ~30x slowdown vs naive bootstrap. Worth it.

---

## 3. Wilson interval vs percentile bootstrap

**Where it showed up:** QA file in `transitions_qa.json`.

For a single binomial proportion (e.g. "how often does action X follow action Y?"),
**Wilson** gives a closed-form CI that is well-behaved near 0 and 1 and requires no
resampling. Percentile bootstrap on the same proportion is noisier and can collapse
to [0, 0] for rare events (we saw this for low-frequency "Other" categories -- it
broke one of our tests until we added tolerance).

**Rule of thumb:** use Wilson for simple binomials; use bootstrap when the statistic
is complex (a difference, a ratio, a KL-divergence) or when clustering matters.

---

## 4. Mixed-effects linear models -- why not OLS with dummies?

**Where it showed up:** `scripts/07c_mixedlm.py`, team-level HCA variation.

With 18 teams x 10 seasons, team-season fixed effects cost 180 parameters. Random
effects shrink team-specific intercepts toward the league mean, so small-sample teams
don't get wild estimates. This is partial pooling, and it buys two things:

1. Honest uncertainty: CIs on per-team HCA widen when a team has few games.
2. Better out-of-sample: the league-mean is a better prior than "this team's 14 games".

**Our finding:** fixed intercept +3.88 pts/game with team random slopes on
`attendance_ratio`. The attendance slope varies substantially across teams (dashboard
tab 3), which a global OLS would hide entirely.

---

## 5. Difference-in-differences with three regimes

**Where it showed up:** COVID natural experiment (`scripts/08_covid_experiment.py`).

Standard DiD is two groups x two times. We had three regimes (pre / during / post
closed-doors) and needed to know: is post = pre (full recovery), or is there a
permanent crowd effect?

**Setup:** regress `point_diff ~ is_home * regime` with `regime in {pre, covid,
post}`. The `is_home:post - is_home:pre` contrast answers "did HCA permanently
change?". The `is_home:covid - is_home:pre` contrast answers "what happens with no
crowd?".

**Result:** post - pre CI crosses zero -> HCA recovered. covid - pre is negative but
CI also crosses zero -> crowd effect is directionally right but not detectable at
this sample size. We report this honestly instead of forcing a conclusion.

**Takeaway:** the two-by-two DiD is a special case; write out the contrast you care
about before running the regression.

---

## 6. Difference in proportions as a test statistic

**Where it showed up:** COVID DiD on home win-rate.

For two binomial rates with known n (e.g. home win-rate pre-COVID vs during), the
standard error is sqrt(p1*(1-p1)/n1 + p2*(1-p2)/n2). Don't trust the bootstrap for
rate differences when you can compute this in closed form and sanity-check against
it.

---

## 7. Possession as the unit of analysis

**Where it showed up:** HCA x transitions attribution (`scripts/14_hca_x_transitions.py`).

**Wrong:** sum up "points gained on post-2FGM possessions at home minus away" +
"points gained on post-TO possessions" + ... across all 19 source actions and claim
that sum as the HCA contribution. You double-count events that flow into the same
possession.

**Right:** compute a single volume-weighted mean `delta_ppp` (points per offensive
possession, home minus away) across all sources, then scale by possessions per team
per game. That gives one number -- how much better home teams are per possession --
that scales up to a pts/game attribution linearly.

**Our number:** weighted delta PPP = +0.049, possessions per team per game ~74,
attribution = +3.63 pts/game out of a +3.88 observed HCA = **94% explained by
possession-level efficiency**.

This was one of the most important lessons of the project: the right unit of
analysis turns a messy per-source explainer into a clean, defensible single-number
attribution.

---

## 8. Markov chains -- first-order and second-order

**Where it showed up:** `12_transitions.py` (Q0/Q1/Q2) and `12b_bigrams.py` (bigrams).

A first-order chain answers "what's the distribution of action-at-time-t+1 given
action-at-time-t?". Three separate chains because "next" has three meanings:

- **Q0:** literal next event in the event stream (may be a paired twin -- see below).
- **Q1:** next action by the *opponent*.
- **Q2:** next action by the *same team's next offensive possession* (skip the
  opponent's possession entirely).

A second-order chain asks "given two steps of history, what's next?". We only
computed these for the top-6 source actions because the state space explodes
(31^3 = ~30k triples, most with <5 observations). Subsetting to top-6 * top-5
storylines keeps it readable and every cell has meaningful n.

**Example:** after a committed foul (`CM`), the top storyline is `CM -> RV -> FTM`
at 24.8%. That's "foul, foul drawn, made free throw" -- a single causal chain across
two teams.

---

## 9. KL divergence for "how different is this team?"

**Where it showed up:** per-team distinctiveness panel in `13_transitions_dashboard.py`.

KL(team || league) measures how surprising a team's Q1 distribution is relative to
the league baseline. High KL = quirky team. Low KL = plays like the median team.

**Caveat:** KL blows up on zero cells (log(0) = -inf). We smooth with a small epsilon
and also report Jensen-Shannon divergence (symmetric, bounded in [0, log 2]) for
team pairs because JSD is more interpretable -- 0 = identical, log 2 = no overlap.

---

## 10. Shannon entropy and Gini for concentration

**Where it showed up:** `transitions_concentration.json`.

Two complementary ways to summarize "how spiky is this action's distribution?":

- **Entropy:** expected surprise in bits. Lower = more predictable.
- **Gini:** area between the Lorenz curve and the diagonal. Higher = more unequal.

Why both? Entropy is information-theoretic (nice for the ML crowd), Gini is
economics-flavored (nice for talks). They correlate ~0.95 on our data, so in
practice reporting one is enough. We show both for pedagogy.

---

## 11. Calibration curve + ROC, not just accuracy

**Where it showed up:** model comparison in `06_ml_logistic.py` and `07_ml_trees.py`.

Accuracy is the least informative metric for a probabilistic classifier. Two models
at 65.7% accuracy can have very different Brier scores and calibration.

**What we report:**

- **Brier score:** the mean squared error of predicted probability vs outcome.
- **Calibration curve:** decile-bin the predictions, plot observed frequency vs
  predicted. A perfectly calibrated model is on the diagonal.
- **ROC:** discrimination quality, independent of threshold.

**Why it matters:** LightGBM and RF both beat logistic on Brier by ~0.002, which is
real but tiny. The story isn't "ML wins" -- it's "Elo + attendance + rest covers
almost everything a tree can find". Reporting accuracy alone would have hidden that.

---

## 12. OLS residual intercept as "what I can't explain"

**Where it showed up:** mechanism decomposition.

Regressing home margin on (eFG%, TOV, OREB, FTR, PF) all as paired differentials,
the intercept captures the residual home advantage that *isn't* explained by any
measurable box-score gap. On our data the intercept is +2.37 pts, meaning ~63% of
HCA is "something else" -- travel, sleep, schedule, clutch execution, referee
uncertainty quantification.

This is a feature, not a bug: it tells me where to look next. In this project it
pointed toward play-by-play -- which later (via the PPP attribution) explained 94%
of HCA at the possession level. Two different models, two different lenses, and
they agree on direction.

---

## 13. Paired-event artifacts (data, not method)

**Where it showed up:** `AG -> FV` at 82% in the Q0 chain.

Some APIs log the *same incident* twice. A block is logged once as `AG` (shot
blocked, shooter's view) and once as `FV` (block, defender's view). They always
appear adjacent in the event stream, so a first-order Markov chain on the raw
stream shows `P(FV | AG) ~ 82%` -- that's data ordering, not basketball.

**Fix:** surface this as a warning banner in the dashboard, and document it in the
readme. Don't silently drop paired events, because some analyses want them.

**Lesson:** always inspect the top-1 transitions manually before trusting any chain.
If a cell is >80% it's usually either trivial (paired event) or wrong (bug).

---

## 14. Sample-first execution

**Where it showed up:** every script in `scripts/`.

Every analysis ran on a 1-2 season sample first (100-300 games) before the full
10-season run. The sample catches schema bugs, performance cliffs, and wrong-unit
errors in minutes instead of hours.

**What this saved us from:** the `game_id`-not-season-unique bug that collapsed 2,564
of 2,897 games in the mechanism pivot would have wasted a 40-minute full run.
Caught on the 2-season sample in 90 seconds.

**The discipline:** always ship the script with a `--sample N` flag and use it.
Don't disable it "just this once".

---

## 15. Data layer separation

**Where it showed up:** `raw/ -> bronze/ -> silver/ -> gold/ -> warehouse.sqlite`.

- **raw:** exactly what the API returned, gzipped. Never rewritten.
- **bronze:** flattened to typed columns but no dedup, no joins.
- **silver:** dedup + joins + derived columns. This is what analyses read.
- **gold:** aggregates per analysis (HCA per team per season, etc).
- **warehouse:** SQLite, ad-hoc queries for sanity checks.

**Why the split matters:** every bug we caught was at a specific layer. Raw was
always right (API is source of truth). Bronze caught type and null issues. Silver
caught join and dedup issues. Keeping them separate made it trivial to trace where a
number first went wrong.

---

## 16. Provenance for free

**Where it showed up:** `ingest_manifest.parquet`, stamped dashboard footers, commit
SHA in every report.

Every artifact carries the commit SHA and UTC timestamp of when it was built. That
means anyone (including future-me) can check out that SHA and reproduce the exact
number they saw.

**Cost:** one small script (`stamp_dashboards.py`) and a `git rev-parse --short`
call in each report generator. Saves hours of "which version was this from?".

---

## 17. Tests as invariants, not regression bait

**Where it showed up:** `tests/test_ingest.py`, `tests/test_transitions.py`.

These aren't unit tests in the Java sense. They're claims about the data that must
hold for the analysis to be valid:

- Every game has exactly one home team and one away team.
- No duplicate `(season, game_id)` rows.
- Transition probabilities sum to 1 within (question, source, split).
- CIs contain the point estimate for the top-1 action.

When the data or code drifts, one of these fires and tells me *where*. Much more
useful than "does `parse_game` return the right dict?".

---

## 18. Reporting effects with uncertainty, always

**Where it showed up:** everywhere.

Every number in the final report has either a 95% CI, a p-value, or an explicit
"directional only -- CI crosses zero" hedge. This is non-negotiable for a learning
artifact; without it the report is marketing.

**The specific discipline:** if I catch myself writing "X is Y", I ask "what's the
uncertainty on Y?" and if I can't answer, I don't publish the claim.
