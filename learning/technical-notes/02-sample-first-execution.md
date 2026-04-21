# Technical note 02 -- sample-first execution pattern

## The rule

Every script supports two modes via env vars:

| Var           | Default | Effect                                                              |
|---------------|---------|---------------------------------------------------------------------|
| `ELH_SAMPLE`  | `1`     | Small slice (one season, ~20 games). <10s runtime.                  |
| `ELH_SAMPLE=0`| ---     | Full 10-season run. 1-10 minutes per phase depending on modelling.  |
| `ELH_MOCK`    | `auto`  | `1` forces offline mock data; `0` forces live; `auto` detects.      |

## Why

- Iteration speed matters most early. A 4-second sample run lets you change a chart label or a
  feature and see the result immediately.
- Full runs are confirmation, not exploration. Switch to full only when the sample looks right.
- Mock mode de-risks network outages. The plumbing is identical; only the data source changes.

## Dashboards show the mode

Every dashboard renders a banner at the top showing `MODE: SAMPLE (n seasons)` or `MODE: FULL`.
This prevents the "I was looking at sample data the whole time" class of mistake.

## Tradeoffs

- Mock data exaggerates HCA slightly (+2.9 pts vs real-world ~2.8) and compresses the COVID
  effect, but preserves the directional signal we need to validate the pipeline.
- Mock data has no play-by-play, shot locations, or referees, so D04-17 through D04-20 render
  placeholders.
