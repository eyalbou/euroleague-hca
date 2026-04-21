"""Load silver + gold parquet tables into data/warehouse.db (SQLite) for ad-hoc SQL."""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import pandas as pd

from euroleague_hca.config import GOLD_DIR, SILVER_DIR, WAREHOUSE_DB

log = logging.getLogger("warehouse")


def _load_dir(conn: sqlite3.Connection, dir_: Path) -> list[str]:
    loaded: list[str] = []
    if not dir_.exists():
        return loaded
    for pq in sorted(dir_.glob("*.parquet")):
        name = pq.stem
        df = pd.read_parquet(pq)
        if df.empty:
            continue
        df.to_sql(name, conn, if_exists="replace", index=False)
        loaded.append(name)
    return loaded


def load() -> dict[str, list[str]]:
    """Build the SQLite warehouse from silver + gold parquet files."""
    conn = sqlite3.connect(WAREHOUSE_DB)
    try:
        silver = _load_dir(conn, SILVER_DIR)
        gold = _load_dir(conn, GOLD_DIR)
        conn.commit()
    finally:
        conn.close()
    log.info("warehouse loaded: silver=%s gold=%s", silver, gold)
    return {"silver": silver, "gold": gold}


def query(sql: str) -> pd.DataFrame:
    conn = sqlite3.connect(WAREHOUSE_DB)
    try:
        return pd.read_sql(sql, conn)
    finally:
        conn.close()
