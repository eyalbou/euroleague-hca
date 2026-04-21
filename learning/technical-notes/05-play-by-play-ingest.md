# 05 -- Play-by-play ingestion

## Why not the Swagger API

The v2/v3 Swagger API (`api-live.euroleague.net`) that we use for games / boxscores
does **not** cover play-by-play. The PBP stream lives on a separate host used by
the EuroLeague website itself:

```
GET https://live.euroleague.net/api/PlaybyPlay?gamecode=<int>&seasoncode=E<year>
```

Because of the host difference, a new client module was added:
`euroleague_hca.ingest.live_direct` -- intentionally kept separate from
`swagger_direct` so no cache or base-URL mix-up is possible.

Reference: `giasemidis/euroleague_api` uses the same URL and documents the ordering
gotcha (see below).

## Response shape gotchas

1. **Per-quarter arrays, not a flat event stream.**  Top-level keys are
   `FirstQuarter`, `SecondQuarter`, `ThirdQuarter`, `ForthQuarter` (the typo is in the API)
   and `ExtraTime`. Our parser iterates them in this fixed order and flattens.

2. **`NUMBEROFPLAY` is unreliable.** Use the array position within each quarter as
   the ordering key (`period_arr_idx`), then emit a monotonic cross-period
   `event_idx` on top. The reference wrapper ships a `TRUE_NUMBEROFPLAY` fix for
   the same reason -- we avoid the problem by never depending on it.

3. **Padded strings.** `CODETEAM`, `PLAYER_ID`, `PLAYTYPE`, `MARKERTIME`, `DORSAL`
   arrive padded to 10 chars with trailing spaces. We strip them at ingest.

4. **`is_home` is derivable at parse time.** Because the response includes both
   `CodeTeamA` (home) and `CodeTeamB` (away) codes at the top level, we tag
   `is_home = (CODETEAM == CodeTeamA)` during the initial flatten -- no join needed.

5. **Clock / admin events have `CODETEAM=""`.** Examples: `BP` (begin period),
   `EP` (end period), `TOUT_TV` (TV timeout), `JB` (jump ball -- actually does
   carry a team). Their NULL-team rate is ~2% of all events; the silver layer
   tags them with `is_action=0` so transition analysis skips them cleanly.

## Action-code catalog (observed on 2024-25)

31 distinct codes. The primary basketball actions:

| Code   | Meaning                                   | 2024-25 count |
|--------|-------------------------------------------|---------------|
| IN/OUT | Player substitution (paired events)       | 19,180 / 19,180 |
| D      | Defensive rebound                         | 15,283 |
| 2FGM   | Made 2-pointer                            | 13,556 |
| RV     | Foul drawn                                | 13,342 |
| AS     | Assist (logged immediately after 2FGM/3FGM) | 12,166 |
| CM     | Foul committed                            | 11,959 |
| 3FGA   | Missed 3-pointer                          | 10,942 |
| 2FGA   | Missed 2-pointer                          | 10,832 |
| FTM    | Made free throw                           | 9,660 |
| TO     | Turnover                                  | 8,129 |
| O      | Offensive rebound                         | 7,126 |
| 3FGM   | Made 3-pointer                            | 6,203 |
| ST     | Steal                                     | 4,254 |
| FTA    | Missed free throw                         | 2,732 |
| TOUT   | Team timeout                              | 2,236 |
| AG     | Shot rejected (shooter-side of a block)   | 1,574 |
| FV     | Block (defender-side)                     | 1,574 |
| OF     | Offensive foul                            | 1,185 |
| CMU    | Unsportsmanlike foul                      | 196 |
| CMT    | Technical foul                            | 159 |
| CMD    | Disqualifying foul                        | 3 |

Note: `AG` and `FV` have **identical counts** (1574) because they are paired
events -- the same block is logged twice, once from shooter, once from defender.
For Q1 analysis, P(FV | source=AG) sits at ~86% simply because they are always
logged adjacently; this is a data-ordering artifact, not a basketball insight.

## Closed-doors flag

`fact_game.attendance == 0` is the closed-doors signal. Concentration by season:

| Season  | Total games | Attendance=0 |
|---------|-------------|--------------|
| 2019-20 | 252 | 3 |
| 2020-21 | 328 | 251 |
| 2021-22 | 299 | 7 |
| 2022-23 | 328 | 2 |
| 2023-24 | 331 | 16 |
| 2024-25 | 330 | 3 |

Propagated onto every event during silver build (`silver.py::build_silver` joins
`fact_game` to each event row and adds `closed_doors = int(attendance == 0)`).

## Performance

* ~1.0 s / game pull rate (with retry + 5 req/s ceiling).
* Cache hit is ~0.3 ms / game.
* 330 games (2024-25 only) -> 176,483 events -> 378 KB dashboard payload.
* Full 10-season estimate: ~2,900 games -> ~1.55M events, cache ~150 MB.
