# ADR: silver dedup must include `season` in the key

Status: accepted (2026-04-17)

## Context

`src/euroleague_hca/silver.py::build_silver` deduped `fact_game` on
`subset=["game_id"]`. In the EuroLeague Swagger API, `game_id` is the
integer `gameCode` that *resets each season* (range roughly 1-350).

As a result, only the first observation of each `game_id` across all
seasons survived the dedup, collapsing 3,597 bronze rows into 333 silver
rows -- we were silently throwing away 90% of the data set before any
analysis ran. Downstream phases (ML, COVID experiment, mechanism analysis)
all ran on the reduced set without warning.

## Decision

Dedup key is now `subset=["season", "game_id"]`. The bronze layer is
season-partitioned and the `write_boxscore_bronze` / `write_bronze`
writers `shutil.rmtree` their target before writing to guarantee
idempotency.

## Secondary decisions taken with this one

- `11_mechanisms.py::compute_mechanisms` now pivots paired home-away
  differentials on `["season", "game_id"]` rather than `"game_id"` for
  the same reason. Without that fix, only 333 of 2,897 games
  contributed to the OLS decomposition.

- `gold.py` now falls back to any-season venue capacity when a venue
  has no `(venue_code, season)` row, since the v3 venues endpoint
  gives only one capacity per venue (stored with `season=0`). Previously
  all 2,897 home games had null `attendance_ratio`.

## Why we didn't see this earlier

Mock mode wrote one game per (season, game_id) combination with unique
identifiers (hash-prefixed), so the bad dedup key looked innocuous.
Only when we pulled live data -- where gameCode is an integer that wraps
each season -- did the bug manifest. Lesson: the mock path should
replicate the ID-collision property of the real API.

## Action items

- [x] Silver dedup on (season, game_id)
- [x] Mechanism pivot on (season, game_id)
- [x] Gold capacity fallback for season=0 venues
- [x] Verified by QA SQL: 2,897 games, 62.4% home-win rate, HCA +3.78
