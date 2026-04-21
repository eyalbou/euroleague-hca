"""Live EuroLeague API -> bronze converter.

Converts the rich `list_games` response from the v2 Swagger API into the same bronze schema
the mock pipeline produces, so all downstream phases work unchanged. Per-(season, game_code)
caching in `swagger_direct` doubles as the resume-checkpoint -- if a season's list is already
on disk, we re-use it.

The list_games endpoint already includes everything we need for Phase 3:
- gameCode, season, round, phaseType (RS/PI/PO/FF)
- local/road clubs (code, name, scores, per-quarter partials)
- venue (code, name, capacity)
- audience, played flag, date

Box scores (FGM/FGA/3PM/3PA/FTM/FTA/ORB/DRB/AST/STL/BLK/TOV/PF) come in Phase 4 via the
separate `boxscore` endpoint.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from euroleague_hca import config
from euroleague_hca.ingest import swagger_direct as sw

log = logging.getLogger("ingest.live")

# Phase code -> our standardized values
PHASE_MAP = {
    "RS": "regular_season",
    "TS": "top16",  # legacy EuroLeague Top-16 format (2015-2018 era)
    "PI": "play_in",
    "PO": "playoffs",
    "FF": "final_four",
}


def _safe_int(x: Any, default: int | None = None) -> int | None:
    try:
        return int(x) if x is not None else default
    except (TypeError, ValueError):
        return default


def _flatten_game(g: dict, season: int) -> dict | None:
    """Convert one list_games row into our flat fact_game schema. Returns None on bad rows."""
    if not g.get("played"):
        return None  # skip unplayed games (current season in-progress)

    local = g.get("local") or {}
    road = g.get("road") or {}
    home_club = local.get("club") or {}
    away_club = road.get("club") or {}
    venue = g.get("venue") or {}

    home_score = _safe_int(local.get("score"))
    away_score = _safe_int(road.get("score"))
    if home_score is None or away_score is None:
        return None

    audience = _safe_int(g.get("audience"), default=0) or 0
    capacity = _safe_int(venue.get("capacity"), default=0) or 0

    phase_code = (g.get("phaseType") or {}).get("code", "")

    # ISO date -> python date
    try:
        date_str = g.get("date") or g.get("utcDate") or g.get("localDate")
        date = datetime.fromisoformat(date_str.replace("Z", "+00:00")).date() if date_str else None
    except (ValueError, AttributeError):
        date = None

    return {
        "game_id": g.get("identifier") or f"{season}_{g.get('gameCode')}",
        "game_code": _safe_int(g.get("gameCode")) or 0,
        "season": season,
        "date": pd.Timestamp(date) if date else pd.NaT,
        "round": _safe_int(g.get("round"), default=0) or 0,
        "phase_code": phase_code,
        "phase": PHASE_MAP.get(phase_code, phase_code.lower() or "unknown"),
        "is_playoff": phase_code in ("PO", "FF"),
        "is_neutral": bool(g.get("isNeutralVenue", False)),
        "home_team_id": home_club.get("code", ""),
        "home_team_name": home_club.get("name", ""),
        "away_team_id": away_club.get("code", ""),
        "away_team_name": away_club.get("name", ""),
        "home_pts": home_score,
        "away_pts": away_score,
        "home_margin": home_score - away_score,
        "home_win": home_score > away_score,
        "venue_code": venue.get("code", ""),
        "venue_name": venue.get("name", ""),
        "arena_capacity": capacity,
        "attendance": audience,
        "attendance_source": "api",
        "attendance_ratio": (audience / capacity) if capacity > 0 else 0.0,
        "data_source": "live",
    }


def _flatten_team(g: dict) -> list[dict]:
    """Pull the two club records out of a game; downstream we dedupe."""
    out = []
    for side in ("local", "road"):
        c = (g.get(side) or {}).get("club") or {}
        if c.get("code"):
            name = c.get("name", "")
            out.append({
                "team_id": c["code"],
                "name": name,
                "name_current": name,  # alias to keep downstream scripts unchanged
                "abbrev": c.get("abbreviatedName", ""),
                "tv_code": c.get("tvCode", ""),
            })
    return out


def _flatten_venue(g: dict, season: int) -> dict | None:
    v = g.get("venue") or {}
    if not v.get("code"):
        return None
    return {
        "venue_code": v["code"],
        "venue_name": v.get("name", ""),
        "season": season,
        "capacity": _safe_int(v.get("capacity"), default=0) or 0,
        "address": v.get("address", ""),
    }


def pull_seasons(seasons: list[int], competition: str = "E") -> dict[str, pd.DataFrame]:
    """Pull list_games for each season; return bronze-shaped DataFrames keyed by entity name."""
    games_rows: list[dict] = []
    teams_rows: list[dict] = []
    venues_rows: list[dict] = []
    manifest_rows: list[dict] = []

    for s in seasons:
        log.info("pulling season %d (competition=%s)", s, competition)
        games = sw.list_games(s, competition=competition)
        log.info("  -> %d game records returned", len(games))

        kept = 0
        for g in games:
            row = _flatten_game(g, s)
            if row:
                games_rows.append(row)
                kept += 1
            for t in _flatten_team(g):
                teams_rows.append(t)
            v = _flatten_venue(g, s)
            if v:
                venues_rows.append(v)

        manifest_rows.append({
            "run_id": datetime.utcnow().strftime("%Y%m%d-%H%M%S"),
            "source": "live",
            "endpoint": "games_list",
            "url": f"v2/competitions/{competition}/seasons/{competition}{s}/games",
            "params": json.dumps({"season": s, "competition": competition}),
            "timestamp": datetime.utcnow().isoformat(),
            "http_status": 200,
            "rows_returned": kept,
            "file_path": str(config.RAW_DIR / "swagger" / "games_list" / str(s)),
            "content_hash": hashlib.md5(f"{competition}{s}".encode()).hexdigest()[:10],
        })
        log.info("  -> %d played games kept (skipped %d unplayed)", kept, len(games) - kept)

    fact_game = pd.DataFrame(games_rows)
    dim_team = pd.DataFrame(teams_rows).drop_duplicates(subset=["team_id"]).reset_index(drop=True) if teams_rows else pd.DataFrame()
    # venue can change capacity year to year (renovations, neutral sites) -- key by (season, venue)
    dim_venue_season = (
        pd.DataFrame(venues_rows).drop_duplicates(subset=["season", "venue_code"]).reset_index(drop=True)
        if venues_rows else pd.DataFrame()
    )
    manifest = pd.DataFrame(manifest_rows)

    return {
        "fact_game": fact_game,
        "dim_team": dim_team,
        "dim_venue_season": dim_venue_season,
        "manifest": manifest,
    }


def write_bronze(frames: dict[str, pd.DataFrame]) -> dict[str, int]:
    """Write the live bronze parquet files using the same path layout as the mock pipeline.
    Idempotent -- entity dirs are blown away before writing (same fix as the 2023-duplicates bug).
    """
    import shutil

    import pyarrow as pa
    import pyarrow.parquet as pq

    counts = {}
    for entity in ("fact_game", "dim_team", "dim_venue_season"):
        df = frames.get(entity, pd.DataFrame())
        if df.empty:
            counts[entity] = 0
            continue

        out = config.BRONZE_DIR / entity
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True, exist_ok=True)

        if "season" in df.columns and entity == "fact_game":
            table = pa.Table.from_pandas(df, preserve_index=False)
            pq.write_to_dataset(table, root_path=str(out), partition_cols=["season"])
        else:
            pq.write_table(pa.Table.from_pandas(df, preserve_index=False), out / "part.parquet")

        counts[entity] = len(df)
        log.info("bronze %s: %d rows", entity, len(df))

    # also write an EMPTY shell for fact_game_team_stats so silver doesn't break
    # (Phase 4 fills it for real)
    empty_stats = config.BRONZE_DIR / "fact_game_team_stats"
    if empty_stats.exists():
        shutil.rmtree(empty_stats)
    empty_stats.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pandas(pd.DataFrame(columns=["game_id", "team_id", "season"]), preserve_index=False),
        empty_stats / "part.parquet",
    )

    return counts


def _flatten_boxscore_team(bs_side: dict, game_id: str, game_code: int, season: int,
                            team_id: str, is_home: bool) -> dict | None:
    """Flatten one side of a boxscore ('local' or 'road') into a team-game stats row."""
    total = (bs_side or {}).get("total") or {}
    if not total:
        return None
    pts = total.get("points", 0) or 0
    fga = total.get("fieldGoalsAttemptedTotal", 0) or 0
    fgm = total.get("fieldGoalsMadeTotal", 0) or 0
    fga2 = total.get("fieldGoalsAttempted2", 0) or 0
    fgm2 = total.get("fieldGoalsMade2", 0) or 0
    fga3 = total.get("fieldGoalsAttempted3", 0) or 0
    fgm3 = total.get("fieldGoalsMade3", 0) or 0
    fta = total.get("freeThrowsAttempted", 0) or 0
    ftm = total.get("freeThrowsMade", 0) or 0
    oreb = total.get("offensiveRebounds", 0) or 0
    dreb = total.get("defensiveRebounds", 0) or 0
    treb = total.get("totalRebounds", 0) or 0
    ast = total.get("assistances", 0) or 0
    stl = total.get("steals", 0) or 0
    tov = total.get("turnovers", 0) or 0
    blk = total.get("blocksFavour", 0) or 0
    pf = total.get("foulsCommited", 0) or 0
    pf_drawn = total.get("foulsReceived", 0) or 0

    # Possessions (Oliver/Kubatko standard formula, single-team approximation)
    possessions = fga + 0.44 * fta - oreb + tov

    # Derived shooting pcts (NaN-safe)
    efg_pct = (fgm + 0.5 * fgm3) / fga if fga > 0 else None
    ts_pct = pts / (2 * (fga + 0.44 * fta)) if (fga + 0.44 * fta) > 0 else None
    fg2_pct = fgm2 / fga2 if fga2 > 0 else None
    fg3_pct = fgm3 / fga3 if fga3 > 0 else None
    ft_pct = ftm / fta if fta > 0 else None

    return {
        "game_id": game_id,
        "game_code": game_code,
        "season": season,
        "team_id": team_id,
        "is_home": int(is_home),
        "points": int(pts),
        "fga": int(fga), "fgm": int(fgm),
        "fga2": int(fga2), "fgm2": int(fgm2),
        "fga3": int(fga3), "fgm3": int(fgm3),
        "fta": int(fta), "ftm": int(ftm),
        "oreb": int(oreb), "dreb": int(dreb), "treb": int(treb),
        "ast": int(ast), "stl": int(stl), "tov": int(tov), "blk": int(blk),
        "pf": int(pf), "pf_drawn": int(pf_drawn),
        "efg_pct": efg_pct, "ts_pct": ts_pct,
        "fg2_pct": fg2_pct, "fg3_pct": fg3_pct, "ft_pct": ft_pct,
        "possessions": float(possessions),
    }


def pull_boxscores(fact_game: pd.DataFrame, competition: str = "E",
                   log_every: int = 100) -> pd.DataFrame:
    """Pull boxscore for every game in fact_game; return long-format team-game stats.

    Uses the per-call swagger cache, so re-runs skip already-fetched games.
    """
    rows = []
    missing = []
    total = len(fact_game)

    for i, (_, g) in enumerate(fact_game.iterrows(), 1):
        season = int(g["season"])
        # game_code: prefer explicit column; otherwise game_id IS the numeric code
        if "game_code" in g and pd.notna(g.get("game_code")):
            game_code = int(g["game_code"])
        else:
            game_code = int(g["game_id"])
        game_id = g["game_id"]
        home_tid = g["home_team_id"]
        away_tid = g["away_team_id"]

        bs = sw.boxscore(season, game_code, competition=competition)
        if bs is None or not isinstance(bs, dict):
            missing.append((season, game_code))
            continue

        for side, tid, is_home in (("local", home_tid, True), ("road", away_tid, False)):
            r = _flatten_boxscore_team(bs.get(side, {}), game_id, game_code, season, tid, is_home)
            if r:
                rows.append(r)

        if i % log_every == 0:
            log.info("  boxscore progress: %d/%d (%.0f%%, missing=%d)",
                     i, total, i / total * 100, len(missing))

    log.info("pull_boxscores done: %d games -> %d team-game rows (missing=%d)",
             total, len(rows), len(missing))
    return pd.DataFrame(rows)


def write_boxscore_bronze(df: pd.DataFrame) -> int:
    """Write fact_game_team_stats bronze (season-partitioned)."""
    import shutil

    import pyarrow as pa
    import pyarrow.parquet as pq

    if df.empty:
        return 0

    out = config.BRONZE_DIR / "fact_game_team_stats"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    pq.write_to_dataset(pa.Table.from_pandas(df, preserve_index=False),
                        root_path=str(out), partition_cols=["season"])
    log.info("bronze fact_game_team_stats: %d rows written", len(df))
    return len(df)


# -----------------------------------------------------------------------------
# Play-by-play ingestion
# -----------------------------------------------------------------------------

# Quarter keys in chronological order -- note the API typo "ForthQuarter".
_PBP_PERIODS = [
    ("FirstQuarter", 1),
    ("SecondQuarter", 2),
    ("ThirdQuarter", 3),
    ("ForthQuarter", 4),
    ("ExtraTime", 5),
]

# Columns that arrive padded with trailing spaces in the API response.
_STRIP_COLS = ("CODETEAM", "PLAYER_ID", "PLAYTYPE", "MARKERTIME", "DORSAL")


def _flatten_pbp(payload: dict, season: int, game_id: str, game_code: int) -> list[dict]:
    """Turn one PBP response into a flat list of event rows.

    Order is array-position within (period, index-in-quarter). NUMBEROFPLAY is
    recorded but not used for sorting -- the reference package documents it as
    unreliable.
    """
    code_a = (payload.get("CodeTeamA") or "").strip()
    code_b = (payload.get("CodeTeamB") or "").strip()
    rows: list[dict] = []
    event_idx = 0  # monotonic per game across all periods

    for period_key, period_num in _PBP_PERIODS:
        events = payload.get(period_key) or []
        for arr_idx, ev in enumerate(events):
            for c in _STRIP_COLS:
                if c in ev and isinstance(ev.get(c), str):
                    ev[c] = ev[c].strip()
            code_team = ev.get("CODETEAM") or ""
            # is_home: CODETEAM == CodeTeamA; None when CODETEAM is blank (BP/EP etc).
            is_home: int | None
            if not code_team:
                is_home = None
            elif code_team == code_a:
                is_home = 1
            elif code_team == code_b:
                is_home = 0
            else:
                is_home = None

            rows.append({
                "season": season,
                "game_id": game_id,
                "game_code": game_code,
                "event_idx": event_idx,
                "period": period_num,
                "period_arr_idx": arr_idx,
                "action_type": (ev.get("PLAYTYPE") or "").upper() or None,
                "code_team": code_team or None,
                "player_id": (ev.get("PLAYER_ID") or "").strip() or None,
                "player_name": (ev.get("PLAYER") or None) if ev.get("PLAYER") else None,
                "marker_time": ev.get("MARKERTIME") or None,
                "minute": ev.get("MINUTE"),
                "points_home": ev.get("POINTS_A"),
                "points_away": ev.get("POINTS_B"),
                "playinfo": ev.get("PLAYINFO") or None,
                "number_of_play": ev.get("NUMBEROFPLAY"),
                "code_team_home": code_a,
                "code_team_away": code_b,
                "is_home": is_home,
            })
            event_idx += 1

    return rows


def pull_playbyplay(fact_game: pd.DataFrame, competition: str = "E",
                    log_every: int = 50) -> pd.DataFrame:
    """Pull play-by-play for every game in fact_game; return long event rows."""
    from euroleague_hca.ingest import live_direct as ld

    rows: list[dict] = []
    missing: list[tuple[int, int]] = []
    total = len(fact_game)
    t0 = time.time()

    for i, (_, g) in enumerate(fact_game.iterrows(), 1):
        season = int(g["season"])
        if "game_code" in g and pd.notna(g.get("game_code")):
            game_code = int(g["game_code"])
        else:
            game_code = int(g["game_id"])
        game_id = g["game_id"]

        pbp = ld.play_by_play(season, game_code, competition=competition)
        if not pbp or not isinstance(pbp, dict):
            missing.append((season, game_code))
            continue

        rows.extend(_flatten_pbp(pbp, season, game_id, game_code))

        if i % log_every == 0:
            elapsed = time.time() - t0
            rate = i / max(elapsed, 0.01)
            log.info("  pbp progress: %d/%d (%.0f%%, missing=%d, %.1f games/s)",
                     i, total, i / total * 100, len(missing), rate)

    log.info("pull_playbyplay done: %d games -> %d events (missing=%d)",
             total, len(rows), len(missing))
    return pd.DataFrame(rows)


def write_pbp_bronze(df: pd.DataFrame) -> int:
    """Write bronze/fact_game_event (season-partitioned, idempotent)."""
    import shutil

    import pyarrow as pa
    import pyarrow.parquet as pq

    if df.empty:
        return 0

    out = config.BRONZE_DIR / "fact_game_event"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    pq.write_to_dataset(
        pa.Table.from_pandas(df, preserve_index=False),
        root_path=str(out),
        partition_cols=["season"],
    )
    log.info("bronze fact_game_event: %d rows written", len(df))
    return len(df)


# ---------------------------------------------------------------------------


def write_manifest(manifest: pd.DataFrame, mode: str = "append") -> None:
    """Append (or replace) the ingest manifest. Default appends so re-runs keep history."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    p = config.INGEST_MANIFEST
    if mode == "append" and p.exists():
        existing = pd.read_parquet(p)
        manifest = pd.concat([existing, manifest], ignore_index=True)
    pq.write_table(pa.Table.from_pandas(manifest, preserve_index=False), p)
