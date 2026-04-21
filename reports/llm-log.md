# LLM collaboration log

This log records how the LLM (Cursor Composer) was used as a working partner across the project,
not just as a code generator. Each entry has a **prompt summary**, the **LLM output type**, and the
**human decision** that followed -- so we can evaluate *how well the LLM helped* after the project
is done.

Rating scale: U = used as-is, M = modified before use, R = rejected.

---

## 1. Metric ideation

**Prompt summary:** "What are good primary and secondary metrics for measuring home-court advantage
in basketball, beyond naive win-rate? Consider attendance dynamics."

**Output type:** Ranked list of 7 candidates with pros/cons.

**Selected:**
- Home point differential (primary) -- tight, continuous, sample-efficient. [U]
- Home win-rate (context) -- binary, high-level, easy to communicate. [U]
- Attendance-ratio dose-response on point differential (H6). [U]
- Per-team attendance slope (H7). [U]

**Rejected:**
- Foul-rate asymmetry -- requires play-by-play, postponed to extension phase. [R]
- Pace-adjusted differential -- adds noise given we already have Elo. [R]

**Decision:** H1-H7 hypothesis framework.

---

## 2. Hypothesis generation

**Prompt summary:** "Given primary = home margin, attendance ratio = secondary, suggest a
hypothesis set spanning league / team / mechanism / externality."

**Output type:** Seven H-IDs with null/alternative wording, pre-registered test and correction.

**Used:** All seven verbatim into the plan. [U]

**Decision:** Hypotheses pre-registered in the plan before any data was touched, so multiple-
comparison correction (Holm) is defensible.

---

## 3. Study design -- COVID natural experiment

**Prompt summary:** "How should I exploit the 2019-20 / 2020-21 empty-arena period to estimate
the crowd-driven component of HCA?"

**Output type:** Difference-in-differences design with three regimes (pre / covid / post), plus
warnings about confounders (schedule compression, playoff bubbles).

**Used:** Three-regime DiD in `scripts/08_covid_experiment.py`. [M]

**Modifications:** Added per-team parallel plot (D08-4) so we can see heterogeneity rather than
just the mean DiD.

---

## 4. Code review -- Elo implementation

**Prompt summary:** "Review my walk-forward Elo. Does it leak future information? Should HCA be
baked in?"

**Output type:** Code review pointing out that baking HCA into Elo would contaminate the downstream
coefficient, and recommending to keep HCA out of the rating.

**Used:** Kept HCA out of Elo. [U]

**Decision:** Logged in `learning/architecture-decisions/ADR-elo-vs-fe.md`.

---

## 5. Model comparison -- Elo vs team-season FE

**Prompt summary:** "Is Elo actually better than ridge-regularized per-team-season fixed effects
for our held-out log-loss?"

**Output type:** Suggestion to run the head-to-head, which we implemented in
`scripts/07d_ridge_fe.py`.

**Used:** Ran it. Elo and FE are within 0.01 log-loss of each other; Elo wins on dimensionality. [U]

**Decision:** ADR-elo-vs-fe.md, Elo kept as the primary team-strength feature.

---

## 6. Visualization -- which chart for what

**Prompt summary:** "For the attendance dose-response, scatter with LOWESS, binned line, or box per
bucket?"

**Output type:** Binned line + scatter overlay with 95% bootstrap CI. Rationale: LOWESS hides the
sample size per bin.

**Used:** D04-6 uses a binned line with CI bands. [U]

---

## 7. Interpretation narrative

**Prompt summary:** "Given that the league HCA in the mock dataset is +2.94 pts with 62.8% home
win-rate and the COVID DiD is -1.82, write a four-sentence plain-language summary."

**Output type:** Narrative text embedded in `reports/final_report.md`.

**Used:** [M] -- edited to remove hype and add uncertainty bands.

---

## 8. Debugging -- LightGBM OpenMP error

**Prompt summary:** "Library not loaded: @rpath/libomp.dylib when importing lightgbm on macOS."

**Output type:** `brew install libomp`.

**Used:** Fixed immediately. [U]

**Decision:** Logged in `learning/debug-log.md`.

---

## 9. Architecture -- data lake layers

**Prompt summary:** "Propose a data architecture that supports reproducible ad-hoc analysis for
a multi-month project with rolling schema changes."

**Output type:** Five-layer lake (raw json / bronze parquet / silver / gold / SQLite warehouse)
with an `ingest_manifest.parquet` for provenance.

**Used:** All five layers, plus manifest. [U]

---

## How well did the LLM help?

| Area                          | Score (1-5) | Notes                                                  |
|-------------------------------|-------------|--------------------------------------------------------|
| Metric ideation               | 5           | Caught attendance dose-response early.                 |
| Hypothesis framing            | 4           | Clean set, light wording edits.                        |
| Study design (DiD)            | 5           | Surfaced confounders we would have missed.             |
| Code review                   | 5           | Elo contamination catch was material.                  |
| Debugging                     | 5           | Fast on environment issues.                            |
| Chart choice                  | 4           | Occasionally over-suggests chart types.                |
| Narrative                     | 3           | Over-confident copy, needs hedging.                    |
| Data architecture             | 5           | Layered lake + manifest scales.                        |

**Running takeaways:**

1. Use the LLM for **framing** (hypotheses, metrics, study design) before any data work.
2. Use it for **code review**, not just code generation -- the Elo-HCA contamination was the
   clearest example.
3. Tighten its narrative output manually; it drifts toward marketing prose.
4. Log every architectural decision the LLM suggests in an ADR so we can audit whether it
   generalized well.

## Phase 2: Live Data & Mechanisms
- Debugged schema mismatches in live API (e.g., `phaseType` -> `phase_code` mapping, `country` dict parsing).
- Derived the mechanism decomposition formula using OLS regression to quantify the exact point contribution of eFG%, TOV%, ORB%, and FT factors to the overall HCA.
- Wrote narrative explaining that EuroLeague HCA is driven by shooting efficiency and turnovers, unlike the NBA where referee bias (fouls/FTs) dominates.
