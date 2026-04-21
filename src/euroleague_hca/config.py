"""Central configuration. Every script imports from here."""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# -- Scope --
SEASONS_FULL = list(range(2015, 2026))  # 2015-16 through 2025-26 (start year)
COMPETITION = os.environ.get("ELH_COMPETITION", "E")  # EuroLeague (U = EuroCup)

DATA_DIR = PROJECT_ROOT / "data" / COMPETITION
RAW_DIR = DATA_DIR / "raw"
BRONZE_DIR = DATA_DIR / "bronze"
SILVER_DIR = DATA_DIR / "silver"
GOLD_DIR = DATA_DIR / "gold"
REFERENCE_DIR = PROJECT_ROOT / "data" / "reference"
WAREHOUSE_DB = DATA_DIR / "warehouse.db"
INGEST_MANIFEST = DATA_DIR / "ingest_manifest.parquet"

DASHBOARDS_DIR = PROJECT_ROOT / "dashboards"
REPORTS_DIR = PROJECT_ROOT / "reports"
LEARNING_DIR = PROJECT_ROOT / "learning"
LOGS_DIR = PROJECT_ROOT / "logs"

for _d in [
    RAW_DIR,
    BRONZE_DIR,
    SILVER_DIR,
    GOLD_DIR,
    REFERENCE_DIR,
    DASHBOARDS_DIR,
    REPORTS_DIR,
    LEARNING_DIR,
    LOGS_DIR,
]:
    _d.mkdir(parents=True, exist_ok=True)

# -- Sample mode --
SAMPLE_MODE = False
SAMPLE_SEASONS = [2024]  # just 2024-25 in sample
SAMPLE_GAMES_PER_SEASON = 400

# -- API endpoints --
EUROLEAGUE_API_V2 = "https://api-live.euroleague.net/v2"
EUROLEAGUE_API_V3 = "https://api-live.euroleague.net/v3"

# -- Offline fallback --
# If set OR if live API is unreachable, generate deterministic synthetic data.
# Attendance_source, data_source columns are tagged 'mock' so analyses never confuse it with real.
USE_MOCK_DATA = "0"  # "auto" | "1" | "0"

MOCK_SEED = 42


def seasons_active() -> list[int]:
    """Return the season list honoring SAMPLE_MODE."""
    return SAMPLE_SEASONS if SAMPLE_MODE else SEASONS_FULL


def banner() -> str:
    """One-line banner describing the current run mode -- printed by every script."""
    mode = "SAMPLE" if SAMPLE_MODE else "FULL"
    mock = ""
    if USE_MOCK_DATA == "1":
        mock = " (MOCK DATA)"
    return f"[euroleague-hca] mode={mode}{mock} seasons={seasons_active()}"
