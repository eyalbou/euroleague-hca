"""Phase 18 -- parse referee assignments from raw game-header JSON into silver.

Every game header under `data/E/raw/live/game/<season>/<hash>.json.gz` carries
up to 4 referee objects at `referee1..referee4`:

    {
      "code": "OAEF",
      "name": "GARCIA, JUAN CARLOS",
      "alias": "GARCIA GONZALEZ, J.C.",
      "country": {"code": "ESP", "name": "Spain"},
      "active": true
    }

We flatten these into a long-format silver table with one row per
(game, referee, slot) and join on `game_id` from `silver/fact_game.parquet`.

Sample mode runs only the latest season; full mode loops all.
"""
from __future__ import annotations

import argparse
import gzip
import json
import logging
from pathlib import Path

import pandas as pd

from euroleague_hca import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("18_referee_ingest")


def _iter_game_headers(season: int | None = None):
    base = config.RAW_DIR / "live" / "game"
    if season is not None:
        paths = [base / str(season)]
    else:
        paths = sorted(p for p in base.iterdir() if p.is_dir())
    for d in paths:
        if not d.exists():
            continue
        for f in sorted(d.glob("*.json.gz")):
            try:
                with gzip.open(f, "rt") as h:
                    yield int(d.name), json.load(h), f
            except Exception as exc:
                log.warning("could not parse %s: %s", f, exc)


def _extract_refs(season: int, doc: dict) -> list[dict]:
    game_code = doc.get("gameCode")
    if game_code is None:
        return []
    rows: list[dict] = []
    for slot in (1, 2, 3, 4):
        ref = doc.get(f"referee{slot}")
        if not ref or not isinstance(ref, dict):
            continue
        code = (ref.get("code") or "").strip()
        if not code:
            continue
        country = ref.get("country") or {}
        rows.append({
            "season": season,
            "game_id": int(game_code),
            "slot": slot,
            "ref_code": code,
            "ref_name": (ref.get("name") or "").strip(),
            "ref_alias": (ref.get("alias") or "").strip(),
            "ref_country": (country.get("code") or "").strip() if isinstance(country, dict) else "",
            "ref_active": bool(ref.get("active", False)),
        })
    return rows


def build(sample: bool = False) -> pd.DataFrame:
    seasons = [max(config.SEASONS_FULL)] if sample else None
    rows: list[dict] = []
    n_games = 0
    for season, doc, _ in _iter_game_headers(seasons[0] if seasons else None):
        extracted = _extract_refs(season, doc)
        if extracted:
            rows.extend(extracted)
            n_games += 1
    df = pd.DataFrame(rows)
    log.info("parsed %d referee rows from %d header files (sample=%s)",
             len(df), n_games, sample)
    # Hash-named JSON files can duplicate the same game across multiple snapshots --
    # collapse by (season, game_id, slot) keeping the last seen record.
    if not df.empty:
        before = len(df)
        df = df.drop_duplicates(subset=["season", "game_id", "slot"], keep="last")
        log.info("dedup (season, game_id, slot): %d -> %d rows", before, len(df))
    return df


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true")
    args = ap.parse_args()

    df = build(sample=args.sample)
    if df.empty:
        log.error("no referee rows parsed -- aborting")
        return

    # Summary
    log.info("unique referees: %d", df["ref_code"].nunique())
    log.info("unique countries: %d", df["ref_country"].nunique())
    log.info("games covered: %d", df[["season", "game_id"]].drop_duplicates().shape[0])
    per_slot = df.groupby("slot").size()
    log.info("per slot: %s", per_slot.to_dict())

    out = config.SILVER_DIR / "fact_game_referee.parquet"
    df.to_parquet(out, index=False)
    log.info("wrote %s (%.0f KB, %d rows)", out, out.stat().st_size / 1024, len(df))


if __name__ == "__main__":
    main()
