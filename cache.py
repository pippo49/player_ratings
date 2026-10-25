"""JSON cache for parsed match data."""

import json
from datetime import date
from pathlib import Path

from models import Match, PlayerResult, TeamResult

CACHE_DIR = Path(__file__).parent / "data"
CACHE_FILE = CACHE_DIR / "matches.json"


def _match_to_dict(m: Match) -> dict:
    def _player(p: PlayerResult) -> dict:
        return {"name": p.name, "player_id": p.player_id, "games_won": p.games_won}

    def _team(t: TeamResult) -> dict:
        return {"name": t.name, "players": [_player(p) for p in t.players], "total_score": t.total_score}

    return {
        "match_id": m.match_id,
        "season": m.season,
        "division": m.division,
        "date": m.date.isoformat() if m.date else None,
        "home": _team(m.home),
        "away": _team(m.away),
    }


def _dict_to_match(d: dict) -> Match:
    def _player(p: dict) -> PlayerResult:
        return PlayerResult(name=p["name"], player_id=p["player_id"], games_won=p["games_won"])

    def _team(t: dict) -> TeamResult:
        return TeamResult(name=t["name"], players=[_player(p) for p in t["players"]], total_score=t["total_score"])

    return Match(
        match_id=d.get("match_id", ""),
        season=d.get("season", "2025-26"),
        division=d["division"],
        date=date.fromisoformat(d["date"]) if d.get("date") else None,
        home=_team(d["home"]),
        away=_team(d["away"]),
    )


def save_matches(matches: list[Match]) -> Path:
    """Write matches to the JSON cache. Returns the cache file path."""
    CACHE_DIR.mkdir(exist_ok=True)
    data = [_match_to_dict(m) for m in matches]
    CACHE_FILE.write_text(json.dumps(data, indent=2))
    return CACHE_FILE


def load_matches() -> list[Match] | None:
    """Load matches from the JSON cache. Returns None if no cache exists."""
    if not CACHE_FILE.exists():
        return None
    data = json.loads(CACHE_FILE.read_text())
    return [_dict_to_match(d) for d in data]


def merge_matches(existing: list[Match], new: list[Match]) -> tuple[list[Match], int]:
    """Merge new matches into existing, deduplicating by (season, match_id).

    The season is part of the key because match IDs are only known to be
    unique within a season — if they restart each year, keying on the ID
    alone would silently drop a new season's matches as duplicates.

    A fixtures page gives the team score without saying who played, so a
    result can arrive first as a stub with no line-up and later in full, once
    its match card is saved. A full card replaces a stub; a stub never
    replaces anything.

    Returns (merged list, count of newly added matches).
    """
    def detailed(m: Match) -> bool:
        return bool(m.home.players or m.away.players)

    index = {(m.season, m.match_id): i
             for i, m in enumerate(existing) if m.match_id}
    merged = list(existing)
    added = 0
    for m in new:
        key = (m.season, m.match_id)
        if not m.match_id:
            continue
        if key not in index:
            index[key] = len(merged)
            merged.append(m)
            added += 1
        elif detailed(m) and not detailed(merged[index[key]]):
            merged[index[key]] = m      # the card has arrived for a stub
    return merged, added
