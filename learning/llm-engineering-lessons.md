# LLM engineering lessons

Scope: what I learned about *how to work with an LLM as a coding and analysis
partner* across this project. Different from `concepts-learned.md` -- that one is
about statistics and data; this one is about the workflow itself.

Format per lesson: **what went well / what went wrong**, then the **rule** I want
to carry forward.

---

## 1. Plan before you prompt

**What went well:** the most productive sessions always started with a written plan
(`/Users/eyalbou/.cursor/plans/*.plan.md`). When I asked the LLM to build something
off a plan, the output was 80% usable on first try.

**What went wrong:** the times I typed "just add X to the dashboard" without a plan,
I got brittle code that worked for the demo case and broke on the second data slice.
We burned an entire hour rewriting the split-selector UI because I hadn't thought
through that 11 splits wouldn't fit as pill buttons.

**Rule:** for anything larger than a 20-line change, write a plan first. The plan is
cheap; the code is expensive. Cursor's plan mode is the right surface for this.

---

## 2. Sample-first is an LLM thing too, not just a data thing

**What went well:** every big job ran on a 1-2 season sample before the full 10.
The LLM-written code was usually correct on the sample but hit edge cases on the
full run (e.g. a team with zero playoff games, a season with weird phase codes).

**What went wrong:** one script passed on 2023-24 data but took 40 minutes on the
full corpus before failing on a missing column from 2015-16. The LLM hadn't
bothered to check pre-2018 schema.

**Rule:** always tell the LLM "run the sample first, print the schema, *then* scale
up". The LLM will happily write a for-loop over all 10 seasons without ever
inspecting the first one.

---

## 3. The LLM will absolutely write code that silently collapses your data

**What went wrong:** the mechanism-decomposition script pivoted on `game_id`, not
`(season, game_id)`. `game_id` is a small integer that repeats across seasons.
`pd.pivot_table` happily collapsed 2,564 of 2,897 games into 333 rows, and the LLM
didn't flag it. Neither did I -- the dashboard looked fine, but the numbers were
wrong by a factor of 10 in places.

**Rule:** any time the LLM writes a `pivot`, `groupby`, `merge`, or `drop_duplicates`,
I now ask explicitly: "what is the natural key of the left side? Does the right side
have the same key?". If I can't answer in one sentence, the code is wrong.

**Corollary:** add a test for the row count after every merge. `assert len(df) ==
expected_n` catches 80% of these bugs.

---

## 4. Code review prompts beat code generation prompts

**What went well:** asking "review my Elo implementation for data leakage" produced
the single best LLM output of the project -- it caught that baking `is_home` into
the Elo update would contaminate the downstream `is_home` regression coefficient.

**What went wrong:** asking "write me an Elo implementation" the first time gave me
correct-looking code with exactly that bug.

**Rule:** when the code is non-trivial, *write it myself* and ask the LLM to review
it. Reviewing is a tighter task than generating, and the LLM is better at it.
Alternatively: generate, then ask for a second pass as a reviewer with no memory of
the original.

---

## 5. Ask for hypotheses and study design, not just implementations

**What went well:** the COVID difference-in-differences design came from asking
"how should I exploit the 2019-20 empty-arena period?". The LLM suggested three
regimes (pre / covid / post), parallel-trends checks, and warned about confounders
(schedule compression, playoff bubbles). Every one of those warnings ended up
mattering.

**Rule:** the LLM is most valuable at the *study design* layer -- before any code is
written. Once the design is right, implementation is mostly mechanical.

---

## 6. The LLM writes marketing copy unless you beat it out

**What went wrong:** first draft of the final report said "home teams dominate on
their court". Second draft said "remarkable +3.88 pt advantage". Neither is a
defensible statistical claim.

**Rule:** every narrative paragraph gets a manual pass where I replace adjectives
with numbers and add hedges. "Dominate" -> "win 62.4% of home games". "Remarkable
advantage" -> "+3.88 pt intercept, 95% CI [+3.45, +4.31]". If the LLM wrote the
sentence and I can't replace the adjective with a number, the claim is wrong.

---

## 7. Provenance discipline pays back 10x

**What went well:** every report has a commit SHA and UTC timestamp. Every dashboard
HTML has a build footer. Every data artifact came with an `ingest_manifest.parquet`.

**Why it mattered:** when I noticed a number had drifted between Phase B and Phase D,
I could `git checkout <sha>` and reproduce the original. Without the SHA I'd have
spent an afternoon bisecting to find when the change landed.

**Rule:** at the start of any analysis project, add a 20-line `stamp.py` that writes
commit SHA + timestamp into every output. Do this *before* the analysis gets
interesting, because after it gets interesting you'll never remember to.

---

## 8. The LLM log is worth the friction

**What went well:** keeping `reports/llm-log.md` (a running record of every prompt,
output type, and whether I used it as-is / modified / rejected) made the post-mortem
trivially easy. I can now see that the LLM was 5/5 on study design and 3/5 on
narrative, and adjust accordingly next project.

**Rule:** log every LLM-assisted decision in a dedicated file, not just in the chat
transcript. Transcripts are long and hard to grep. A one-line summary per decision
is enough.

---

## 9. Batch small asks, ship big ones

**What went well:** multi-step phases (Phase A, B, C, D) went fastest when I batched
all related asks into one plan and one commit. "Update 12_transitions.py, then
13_transitions_dashboard.py, then stamp the dashboards" as a single prompt was 3x
faster than three separate prompts.

**What went wrong:** the early HCA dashboard was built up one chart at a time, and I
rewrote the layout three times because each new chart made the previous layout feel
cramped.

**Rule:** for a new artifact, design the whole thing first (in a plan or a
wireframe), then ask the LLM to build it in one shot. For incremental work on an
existing artifact, small asks are fine.

---

## 10. Tests are scaffolding for the LLM, not just for me

**What went well:** once `tests/test_transitions.py` was in place, the LLM stopped
breaking `12_transitions.py` between iterations. Every time it refactored the
bootstrap function, the tests caught the regression before the dashboard was
rebuilt.

**Rule:** tests with domain invariants (probabilities sum to 1, CI contains the
point estimate, row count matches) are the single best way to stop LLM refactoring
from introducing subtle bugs. Write them early. Make them cheap to run (ours finish
in 2 seconds on the cached corpus).

---

## 11. The LLM over-engineers defensively, under-engineers optimistically

**Observation:** when I said "make this robust", the LLM wrapped everything in
try/except, added retries, defaulted to empty on every error. When I said "make this
fast", it wrote a one-liner with no error handling.

**Rule:** phrase the ask in terms of *which failure mode is acceptable*. "Make this
robust to network errors, but crash loudly on schema drift" produces better code
than either "robust" or "fast" alone.

---

## 12. Dashboard code benefits from an explicit style spec

**What went well:** providing the LLM with a reference to `eyal-visualization`
style (tokens, spacing, fonts, number formatting) up front made every dashboard in
the project visually coherent.

**What went wrong:** early dashboards drifted -- one used Inter, another used DM
Sans, number formatting was inconsistent (1200 vs 1.2K). Tying everything back to a
shared style doc fixed this.

**Rule:** dashboards need a style contract the LLM can cite. A one-page spec with
color tokens, font stack, spacing grid, and number formatting rules is enough.

---

## 13. Delegate the boring, supervise the interesting

**What went well:** LLM did all the HTML/CSS scaffolding, all the Chart.js
configuration, all the test boilerplate, all the `README.md` content. I spent my
time on: choosing which analyses to run, interpreting results, questioning
surprising findings (the `AG -> FV` 82% chain), writing the narrative.

**Rule:** the LLM's comparative advantage is on code volume and formatting. My
comparative advantage is on judgment -- which question matters, which number is
suspicious, which hedge is honest. Divide the labor accordingly.

---

## 14. Surprising LLM output is a flag, not a feature

**What went wrong:** the first HCA-attribution calculation came out to 140% of
observed HCA -- i.e. the sum of per-source contributions was larger than the HCA
itself. The LLM confidently reported this and suggested a rescaling. I should have
stopped and asked "why would the sum exceed the total?".

**The real answer:** events overlap within possessions, so summing per-event
contributions double-counts. The fix was the volume-weighted mean delta-PPP
approach.

**Rule:** when the LLM reports something that doesn't make physical sense (a
probability > 1, a share > 100%, a CI that doesn't contain the point estimate), the
bug is almost always in the computation, not in the interpretation. Don't let the
LLM rationalize it away. Ask for a derivation.

---

## 15. GitHub Pages + email loop is the right publishing surface

**What went well:** the ship-to-Pages + email loop made iteration on mobile fast.
Every phase ended with: push to `main`, Pages rebuilds in ~30s, email goes out with
a direct link to the new view. I reviewed everything on my phone that afternoon.

**Rule:** for any analysis project meant to be shared, add a one-command "ship"
path early. The LLM writes this quickly, and it changes how often I actually
review the work.

---

## 16. Write for future-you

Every file in `learning/` is written assuming I'll come back to this project in 6
months having forgotten everything. That constraint made the notes better -- no
shorthand, every acronym expanded, every number traced back to the generating
script. It also makes the project recyclable: the next similar analysis (any
basketball league, any sport, any paired-observation study) can start from these
notes instead of from zero.

**Rule:** write the notes as if onboarding a stranger. If you can't explain a
decision in one paragraph of plain language, you don't understand it well enough to
commit it.

---

## Scorecard, revised

Earlier (before PBP + transitions phase):

| Area | Score | Notes |
|------|-------|-------|
| Metric ideation | 5 | Caught attendance dose-response early |
| Hypothesis framing | 4 | Clean set, light wording edits |
| Study design (DiD) | 5 | Surfaced confounders |
| Code review | 5 | Elo contamination catch was material |
| Debugging | 5 | Fast on environment issues |
| Chart choice | 4 | Occasionally over-suggests |
| Narrative | 3 | Over-confident copy, needs hedging |
| Data architecture | 5 | Layered lake + manifest scales |

Adding for Phase D:

| Area | Score | Notes |
|------|-------|-------|
| Complex refactor (11 splits, dropdown UI) | 4 | Needed a second pass for spacing |
| New analysis design (bigrams) | 5 | State-space pruning suggestion was spot on |
| Test-writing under pressure | 4 | First draft had wrong assertions; fixed quickly |
| Publishing pipeline (Pages + email) | 5 | Boilerplate was flawless |
| HCA-PPP attribution (methodological) | 4 | First pass overcounted; second pass clean |

**Overall:** the LLM is a 5/5 on framing, study design, and implementation
scaffolding; a 4/5 on complex refactors and methodological derivations; a 3/5 on
narrative and adjectives. Next project, I'll lean harder on the first bucket and
lighter on the last.
