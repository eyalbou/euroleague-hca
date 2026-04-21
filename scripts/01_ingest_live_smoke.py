import logging
import json
from pathlib import Path
import pandas as pd
import pandera as pa
from pandera.typing import Series
from euroleague_hca.config import RAW_DIR
from euroleague_hca.ingest import swagger_direct

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("smoke_test")

class GameSchema(pa.DataFrameModel):
    gameCode: Series[int]
    season: Series[int]
    homeTeam: Series[str]
    awayTeam: Series[str]
    homeScore: Series[int]
    awayScore: Series[int]
    attendance: Series[int] = pa.Field(nullable=True)
    played: Series[bool]

def check_checkpoint(season: int, endpoint: str) -> bool:
    chk_path = RAW_DIR / "_checkpoints" / f"{endpoint}_{season}.done"
    return chk_path.exists()

def mark_checkpoint(season: int, endpoint: str):
    chk_path = RAW_DIR / "_checkpoints" / f"{endpoint}_{season}.done"
    chk_path.parent.mkdir(parents=True, exist_ok=True)
    chk_path.touch()

def run_smoke_test():
    season = 2024
    log.info(f"Running smoke test for season {season}")
    
    # Checkpoint check
    if check_checkpoint(season, "smoke_test"):
        log.info("Smoke test already completed.")
        return
        
    games = swagger_direct.list_games(season)
    if not games:
        log.error("Failed to fetch games list.")
        return
        
    # Take first 30 games
    smoke_games = games[:30]
    log.info(f"Fetched {len(smoke_games)} games from list. Fetching metadata for first 30.")
    
    records = []
    for g in smoke_games:
        game_code = g.get("gameCode")
        if not game_code:
            continue
            
        meta = swagger_direct.game_metadata(season, game_code)
        if not meta:
            log.warning(f"Failed to fetch metadata for game {game_code}")
            continue
            
        home_team = meta.get("local", {}).get("club", {}).get("code", "")
        away_team = meta.get("road", {}).get("club", {}).get("code", "")
        home_score = meta.get("local", {}).get("score", 0)
        away_score = meta.get("road", {}).get("score", 0)
        attendance = meta.get("attendance", 0)
        played = meta.get("played", False)
        
        records.append({
            "gameCode": game_code,
            "season": season,
            "homeTeam": home_team,
            "awayTeam": away_team,
            "homeScore": home_score,
            "awayScore": away_score,
            "attendance": attendance,
            "played": played
        })
        
    df = pd.DataFrame(records)
    
    # Validate schema
    try:
        GameSchema.validate(df)
        log.info("Schema validation passed!")
    except pa.errors.SchemaError as e:
        log.error(f"Schema validation failed: {e}")
        return
        
    # Write manifest
    manifest_path = RAW_DIR / "live" / f"smoke_manifest_{season}.parquet"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Add data_source
    df["data_source"] = "live"
    df.to_parquet(manifest_path)
    
    mark_checkpoint(season, "smoke_test")
    log.info(f"Smoke test complete. Wrote {len(df)} rows to {manifest_path}")
    
    # Print 5 rows for inspection
    print("\n--- 5 Random Rows for Inspection ---")
    print(df[["gameCode", "homeTeam", "awayTeam", "homeScore", "awayScore", "attendance"]].head(5))

if __name__ == "__main__":
    run_smoke_test()
