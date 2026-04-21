# EuroLeague Home Court Advantage

A self-built analysis pipeline quantifying home court advantage (HCA) in
professional EuroLeague basketball, combining classical statistics, mixed
effects models, and first-order Markov chains over play-by-play data.

**Live dashboard:** https://eyalbou.github.io/euroleague-hca/

## Headline findings

- **+3.88 pts / game** average home advantage (mixed-effects LM intercept).
- **Home teams win 1.75x more often** than on the road (logistic odds ratio).
- **94% of HCA** is explained by possession-level efficiency -- home teams
  score **+0.049 more points per offensive possession** than road teams,
  across *every single one* of the 19 trackable source actions.
- COVID-19 natural experiment confirms HCA recovered to pre-pandemic levels
  once fans returned.

## Pipeline

```
raw/   -> bronze/       -> silver/        -> gold/            -> reports/
Swagger  flat parquet    enriched facts    team-season rollups  *_output.json
JSON     partitioned     (attendance,       used by models       (traceable)
         by season       closed-doors,
                         action groups)
```

Every number in `reports/final_report.md` traces back to a committed
`*_output.json`. Dashboards are regenerated from those JSONs.

## Repo structure

```
euroleague-hca/
├── src/euroleague_hca/       # shared modules (ingest, silver, bronze, config)
├── scripts/                  # Cursor-native `# %%` pipeline scripts (01..17)
├── data/                     # local data lake (gitignored except reference/)
├── reports/                  # JSON outputs + final_report.md (committed)
├── dashboards/               # generated HTML (committed)
├── docs/                     # GitHub Pages root (copy of publishable dashboards)
├── learning/                 # ADRs + technical notes (project memory)
├── tests/                    # pytest invariants on the pipeline outputs
└── logs/                     # run logs (gitignored)
```

## Reproduce locally

```bash
# prerequisites: Python 3.14
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Ingest (caches API responses in data/raw/ gzipped JSON)
python scripts/01_ingest.py            # game headers + boxscores
python scripts/01c_playbyplay.py       # play-by-play (can be re-run safely)

# Build silver + gold
python scripts/02_silver.py
python scripts/03_gold.py

# Run analyses
python scripts/06_logistic.py
python scripts/07_trees.py
python scripts/07c_mixedlm.py
python scripts/08_covid.py
python scripts/11_mechanism.py
python scripts/12_transitions.py
python scripts/14_hca_x_transitions.py

# Rebuild dashboards
python scripts/10_analyst_dashboard.py
python scripts/13_transitions_dashboard.py
python scripts/15_final_report.py
python scripts/16_summary_onepager.py
python scripts/stamp_dashboards.py
python scripts/17_build_docs.py

# Tests
pytest tests/ -q
```

## Data sources

- **`api-live.euroleague.net`** (Swagger v2/v3) -- game headers, boxscores,
  scheduling, attendance.
- **`live.euroleague.net/api/PlaybyPlay`** -- play-by-play events.
- **`data/reference/venue_capacity.csv`** -- curated arena capacities for
  computing `attendance_ratio`.

All API responses are cached locally as gzipped JSON and re-used idempotently.

## Methods

- Classical: paired t-tests, Wilcoxon signed-rank, bootstrap CIs (all
  **clustered at the game level** -- treating events as independent would
  dramatically underestimate variance).
- Regression: OLS mechanism decomposition (eFG%, FT rate, TOV/100, etc.),
  logistic regression with interactions, Ridge on team-season fixed effects.
- Mixed effects: `statsmodels.mixedlm` for per-team attendance slopes.
- Tree models: Random Forest and LightGBM with calibration curves and ROC.
- Natural experiment: Difference-in-differences around the closed-doors
  2019-20 / 2020-21 seasons.
- Markov chains (Q0, Q1, Q2): first-order transition matrices per source
  action, with a refined Q2 that targets the next *offensive* action on the
  same team's next possession, plus KL-divergence ranking of per-team
  distinctiveness.

## Learning artifact

This repo is primarily a **learning exercise in ML engineering**. The
`learning/` folder documents architectural decisions (ADRs) and technical
notes captured during development (API quirks, bootstrap pitfalls, paired-event
artifacts in the PBP data).

## License

MIT. Data belongs to EuroLeague; only derived metrics are redistributed here.
