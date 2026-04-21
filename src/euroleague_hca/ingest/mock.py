"""Deterministic synthetic EuroLeague dataset.

WHY THIS EXISTS
---------------
The live EuroLeague API may not be reachable from every environment (e.g. corporate proxies
block public APIs, or the project needs to run offline). We need the rest of the pipeline --
silver, gold, features, models, dashboards -- to be verifiable end-to-end without waiting on
network.

The mock generator produces the same schema the live ingest would produce, but every row is
tagged `data_source='mock'`. Analyses can always filter on this to guarantee they are only
running on real data.

DESIGN GOALS
------------
* Realistic distributions: ~18 teams, ~34 regular-season games per team per season, ~3500 games
  per 10 seasons.
* Real HCA baked in (~+3.2 points), so the analyses produce a plausible answer that matches
  published EuroLeague HCA (~3 pts).
* Attendance dose-response: stronger HCA when arena is fuller. 2020-21 closed-doors shrinks HCA.
* Per-team variation: some teams have bigger HCA than others; some are more crowd-sensitive.
* Determinism: same seed -> same games every time.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from euroleague_hca.config import MOCK_SEED, RAW_DIR

# 18 fictional teams modeled loosely on real EuroLeague clubs (names fictional to avoid confusion
# with real data -- note the -FC suffix and the prefix E_ on team ids).
TEAMS = [
    ("E_RM", "Real Monarcas", "Madrid", "ESP", "V_RM", 15000),
    ("E_BC", "Barca Basquete", "Barcelona", "ESP", "V_BC", 7500),
    ("E_OL", "Olympiakos Pireus", "Piraeus", "GRE", "V_OL", 14000),
    ("E_PA", "Panathenakos", "Athens", "GRE", "V_PA", 18500),
    ("E_FB", "Fenerbahce BSK", "Istanbul", "TUR", "V_FB", 13000),
    ("E_EF", "Efes SK", "Istanbul", "TUR", "V_EF", 16000),
    ("E_VB", "Virtus Bolonia", "Bologna", "ITA", "V_VB", 8500),
    ("E_EA", "EA7 Milano", "Milan", "ITA", "V_EA", 12700),
    ("E_MA", "Maccabi Telaviv", "Tel Aviv", "ISR", "V_MA", 11000),
    ("E_MO", "Monaco Rocca", "Monaco", "FRA", "V_MO", 5200),
    ("E_AS", "Asvel Lyonnais", "Lyon", "FRA", "V_AS", 5700),
    ("E_PA2", "Paris Olympique", "Paris", "FRA", "V_PA2", 15500),
    ("E_BA", "Baskonia Vita", "Vitoria", "ESP", "V_BA", 15500),
    ("E_AL", "Alba Berlin", "Berlin", "GER", "V_AL", 14500),
    ("E_BM", "Bayern Munchen", "Munich", "GER", "V_BM", 11500),
    ("E_ZS", "Zalgiris Kaunas", "Kaunas", "LTU", "V_ZS", 15400),
    ("E_RC", "Crvena Zvezda", "Belgrade", "SRB", "V_RC", 20000),
    ("E_PBG", "Partizan Bgrd", "Belgrade", "SRB", "V_PBG", 19000),
]

# True HCA per team (points). Varies by team -- this is what analyses should recover.
_TRUE_HCA = {
    "E_RM": 4.5, "E_BC": 3.5, "E_OL": 5.5, "E_PA": 5.0,
    "E_FB": 4.0, "E_EF": 3.8, "E_VB": 3.0, "E_EA": 3.0,
    "E_MA": 3.5, "E_MO": 2.5, "E_AS": 2.0, "E_PA2": 3.0,
    "E_BA": 4.0, "E_AL": 2.8, "E_BM": 2.5, "E_ZS": 5.0,
    "E_RC": 5.5, "E_PBG": 5.2,
}

# True crowd-sensitivity slope per team: how much HCA grows per unit attendance_ratio.
# Positive = teams that need crowd. Small = teams whose HCA is systemic (travel fatigue, rims).
_TRUE_CROWD_SLOPE = {
    "E_RM": 3.0, "E_BC": 2.0, "E_OL": 6.5, "E_PA": 6.0,
    "E_FB": 4.0, "E_EF": 3.0, "E_VB": 2.0, "E_EA": 1.5,
    "E_MA": 5.5, "E_MO": 1.0, "E_AS": 1.0, "E_PA2": 2.0,
    "E_BA": 5.0, "E_AL": 2.5, "E_BM": 1.5, "E_ZS": 6.5,
    "E_RC": 7.0, "E_PBG": 7.0,
}

# Base team strength (Elo-like); higher = better. Varies by season with noise.
_BASE_STRENGTH = {
    "E_RM": 1650, "E_BC": 1620, "E_OL": 1630, "E_PA": 1560, "E_FB": 1610,
    "E_EF": 1625, "E_VB": 1550, "E_EA": 1540, "E_MA": 1555, "E_MO": 1580,
    "E_AS": 1500, "E_PA2": 1530, "E_BA": 1570, "E_AL": 1500, "E_BM": 1530,
    "E_ZS": 1555, "E_RC": 1560, "E_PBG": 1565,
}

LEAGUE_HCA_MEAN = 3.2  # overall league mean (matches published ~3 pts)


@dataclass
class MockGame:
    game_id: str
    season: int
    phase: str
    round: int
    date: str
    home_team_id: str
    away_team_id: str
    venue_code: str
    home_pts: int
    away_pts: int
    overtime: bool
    attendance: int | None
    attendance_source: str
    capacity: int
    is_neutral: bool
    data_source: str = "mock"


def _rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


def _season_strength(team_id: str, season: int, rng: np.random.Generator) -> float:
    return _BASE_STRENGTH[team_id] + rng.normal(0, 25)


def _season_schedule(season: int, teams: list[str], rng: np.random.Generator) -> list[tuple[str, str, int, str]]:
    """Double round-robin: every team plays every other team home and away."""
    rounds: list[tuple[str, str, int, str]] = []
    n = len(teams)
    # Regular season: double round robin (34 games per team w/ 18 teams would be 17*2=34).
    round_num = 0
    pairs_first: list[tuple[str, str]] = [(teams[i], teams[j]) for i in range(n) for j in range(n) if i != j]
    rng.shuffle(pairs_first)
    # Limit per round so calendar looks realistic: ~9 games per round
    games_per_round = 9
    for i, (h, a) in enumerate(pairs_first):
        round_num = i // games_per_round + 1
        rounds.append((h, a, round_num, "RS"))
    # Playoffs: top 8 in single-elim; 4 QF pairs, SF, Final Four.
    # Simplified: just add a few playoff games.
    top8 = sorted(teams, key=lambda t: _BASE_STRENGTH[t], reverse=True)[:8]
    rng.shuffle(top8)
    playoff_round = round_num + 1
    for i in range(4):
        h, a = top8[2 * i], top8[2 * i + 1]
        rounds.append((h, a, playoff_round, "PO"))
        rounds.append((a, h, playoff_round, "PO"))
    return rounds


def _covid_factor(season: int) -> float:
    """Multiplier on attendance. 2020 (= 2020-21 season) is closed doors."""
    if season == 2020:
        return 0.0
    if season == 2021:
        return 0.7  # limited capacity
    return 1.0


def _season_date(season: int, round_num: int) -> str:
    # Rounds run mid-October through early May
    start_month = 10
    # ~8 days between rounds
    day_offset = (round_num - 1) * 8
    import datetime

    d = datetime.date(season, start_month, 15) + datetime.timedelta(days=day_offset)
    return d.isoformat()


def _simulate_game(
    home: str,
    away: str,
    round_num: int,
    phase: str,
    season: int,
    rng: np.random.Generator,
) -> MockGame:
    h_str = _season_strength(home, season, rng)
    a_str = _season_strength(away, season, rng)

    # Attendance
    capacity = next(c for tid, *_, c in TEAMS if tid == home)
    covid = _covid_factor(season)
    if covid == 0.0:
        attendance = 0
        att_source = "closed_doors"
    else:
        # Draw-vs-opponent effect: bigger games (vs top-strength opponent) draw more.
        base_fill = 0.70 + 0.0003 * max(0, a_str - 1500) + rng.normal(0, 0.08)
        fill = float(np.clip(base_fill * covid, 0.0, 1.0))
        attendance = int(capacity * fill)
        att_source = "api" if rng.random() > 0.05 else "missing"
        if att_source == "missing":
            attendance = None

    # HCA: base + crowd slope * (attendance_ratio - 0.8)
    att_ratio = (attendance / capacity) if (attendance is not None) else 0.0
    hca_true = _TRUE_HCA[home] + _TRUE_CROWD_SLOPE[home] * (att_ratio - 0.8)
    if phase == "PO":
        hca_true *= 0.6  # HCA shrinks in playoffs (H3)

    # Margin = strength diff + hca + noise
    mean_margin = (h_str - a_str) / 28.0 + hca_true  # strength scaled to points
    margin = int(round(rng.normal(mean_margin, 9.5)))
    home_pts = int(round(rng.normal(82, 6) + max(margin, 0) / 2))
    away_pts = home_pts - margin
    # clamp
    home_pts = max(55, min(110, home_pts))
    away_pts = max(55, min(110, away_pts))
    overtime = False
    if home_pts == away_pts:
        # tie broken by OT points for home +/- 1
        if rng.random() > 0.5:
            home_pts += 2
        else:
            away_pts += 2
        overtime = True

    game_code = int(hashlib.sha1(f"{season}-{round_num}-{home}-{away}".encode()).hexdigest(), 16) % 10_000
    date = _season_date(season, round_num)
    game_id = f"{season}-{phase}-{game_code:05d}"
    venue_code = next(v for tid, *rest, v, _c in TEAMS if tid == home)

    return MockGame(
        game_id=game_id,
        season=season,
        phase=phase,
        round=round_num,
        date=date,
        home_team_id=home,
        away_team_id=away,
        venue_code=venue_code,
        home_pts=home_pts,
        away_pts=away_pts,
        overtime=overtime,
        attendance=attendance,
        attendance_source=att_source,
        capacity=capacity,
        is_neutral=False,
    )


def generate(seasons: list[int]) -> dict:
    """Generate all mock data for the given seasons and return it as in-memory tables."""
    rng = _rng(MOCK_SEED)
    teams = [t[0] for t in TEAMS]

    games: list[MockGame] = []
    for s in seasons:
        schedule = _season_schedule(s, teams, rng)
        for home, away, rnd, phase in schedule:
            g = _simulate_game(home, away, rnd, phase, s, rng)
            games.append(g)

    dim_team = [
        {"team_id": tid, "name_current": name, "city": city, "country": country,
         "primary_venue_code": vcode, "active_from": 2015, "active_to": 2024}
        for tid, name, city, country, vcode, _cap in TEAMS
    ]
    dim_venue_season = []
    for season in seasons:
        for tid, _name, city, country, vcode, cap in TEAMS:
            dim_venue_season.append({
                "venue_code": vcode, "season": season, "name": f"{city} Arena",
                "city": city, "country": country, "capacity": cap, "is_shared": False,
            })

    fact_game = [
        {
            "game_id": g.game_id, "season": g.season, "phase": g.phase, "round": g.round,
            "date": g.date, "home_team_id": g.home_team_id, "away_team_id": g.away_team_id,
            "venue_code": g.venue_code, "home_pts": g.home_pts, "away_pts": g.away_pts,
            "overtime": g.overtime, "attendance": g.attendance,
            "attendance_source": g.attendance_source, "is_neutral": g.is_neutral,
            "data_source": g.data_source,
        }
        for g in games
    ]

    return {
        "dim_team": dim_team,
        "dim_venue_season": dim_venue_season,
        "fact_game": fact_game,
    }


def write_raw(seasons: list[int]) -> Path:
    """Write raw mock payloads to data/raw/mock/{season}/ so the ingest manifest has something."""
    data = generate(seasons)
    base = RAW_DIR / "mock"
    for season in seasons:
        p = base / str(season)
        p.mkdir(parents=True, exist_ok=True)
        games = [g for g in data["fact_game"] if g["season"] == season]
        with gzip.open(p / "fact_game.json.gz", "wt") as f:
            json.dump(games, f)
    # dims in a season-independent location
    with gzip.open(base / "dim_team.json.gz", "wt") as f:
        json.dump(data["dim_team"], f)
    with gzip.open(base / "dim_venue_season.json.gz", "wt") as f:
        json.dump(data["dim_venue_season"], f)
    return base
