"""Build the JSON payload the web front end runs on.

The front end does all searching, filtering and lineup maths client-side, so
the server only ever has to hand over one document: every rated player, every
team roster, and a little metadata about the data set.
"""

import json
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

from elo import MIN_MATCHES, PlayerRating, calculate_ratings
from models import Match
from scraper import CURRENT_SEASON

OVERRIDE_DIR = Path(__file__).resolve().parent.parent / "data"

# A team match is 9 singles plus 1 doubles, so 10 points are on offer.
SINGLES_PER_MATCH = 9
POINTS_PER_MATCH = 10


def _doubles_report(matches: list[Match]) -> dict:
    """Check that the 9 singles + 1 doubles format holds across the data.

    The doubles itself is not modelled or predicted — the scraped data does
    not say which two players formed the pair. This only confirms the format
    is what we think it is, so the points arithmetic is on solid ground: the
    doubles point is whatever the team total has over its singles wins, and
    the two sides should always split it 0/1.
    """
    recovered = anomalies = home_wins = 0

    for match in matches:
        home_point = match.home.total_score - sum(p.games_won for p in match.home.players)
        away_point = match.away.total_score - sum(p.games_won for p in match.away.players)
        if {home_point, away_point} != {0, 1}:
            anomalies += 1
            continue
        recovered += 1
        home_wins += home_point == 1

    return {
        "matches": len(matches),
        "recovered": recovered,
        "anomalies": anomalies,
        "home_win_rate": round(home_wins / recovered, 4) if recovered else None,
        "format_holds": bool(recovered) and anomalies / max(len(matches), 1) < 0.02,
    }


def season_label(season: str) -> str:
    """"2026-27" -> "Winter 2026/27"."""
    start, end = season.split("-")
    return f"Winter {start}/{end}"


def load_division_overrides(season: str) -> dict[str, int]:
    """Load a hand-or-scraped map of {team name: division} for *season*.

    Before a season's fixtures are published there are no matches to infer
    structure from, but the divisions and teams are already known. This file
    carries that: `data/teams_2026-27.json`, shaped
    ``{"season": "2026-27", "teams": {"Apex 4": 3, ...}}``.

    Returns an empty dict when the file is absent, which is the normal state
    once real fixtures exist.
    """
    path = OVERRIDE_DIR / f"teams_{season}.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    return {name: int(div) for name, div in data.get("teams", {}).items()}


def _seasons_desc(matches: list[Match]) -> list[str]:
    """Seasons present in the data, most recent first."""
    return sorted({m.season for m in matches}, reverse=True)


def _rosters_by_season(matches: list[Match]) -> dict[str, dict[str, dict[str, int]]]:
    """{season: {team: {player_id: appearances}}} across all matches."""
    out: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(int))
    )
    for match in matches:
        for side in (match.home, match.away):
            for player in side.players:
                out[match.season][side.name][player.player_id] += 1
    return {s: {t: dict(p) for t, p in teams.items()} for s, teams in out.items()}


def _divisions_by_season(matches: list[Match]) -> dict[str, dict[str, int]]:
    """{season: {team: division it played most in that season}}."""
    counts: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    for match in matches:
        counts[match.season][match.home.name][match.division] += 1
        counts[match.season][match.away.name][match.division] += 1
    return {
        season: {team: c.most_common(1)[0][0] for team, c in teams.items()}
        for season, teams in counts.items()
    }


def _resolve_teams(
    matches: list[Match],
    ratings: dict[str, PlayerRating],
    season: str,
) -> list[dict]:
    """Build the team list for *season*, carrying rosters forward where needed.

    A team that has already played this season uses this season's roster and
    division. One that has not — the normal case before fixtures start —
    keeps the squad it last fielded, and takes its division from the override
    file if there is one. Each team says which season its roster came from so
    the app can be honest about it.
    """
    rosters = _rosters_by_season(matches)
    divisions = _divisions_by_season(matches)
    overrides = load_division_overrides(season)
    older = [s for s in _seasons_desc(matches) if s != season]

    names = set(overrides) | set(rosters.get(season, {}))
    if not overrides:
        # No structure published yet — fall back to whoever played last.
        for s in older:
            names |= set(rosters.get(s, {}))
            break

    teams = []
    for name in sorted(names):
        roster = rosters.get(season, {}).get(name)
        roster_season = season
        if not roster:
            for s in older:
                if name in rosters.get(s, {}):
                    roster, roster_season = rosters[s][name], s
                    break
        if not roster:
            continue

        division = (
            overrides.get(name)
            or divisions.get(season, {}).get(name)
            or divisions.get(roster_season, {}).get(name)
        )
        if not division:
            continue

        members = [pid for pid in roster if pid in ratings]
        if not members:
            continue
        members.sort(key=lambda pid: ratings[pid].rating, reverse=True)

        teams.append({
            "name": name,
            "division": division,
            "roster_season": roster_season,
            "carried": roster_season != season,
            "players": [{"id": pid, "appearances": roster[pid]} for pid in members],
        })
    return teams


def _player_dict(pr: PlayerRating) -> dict:
    return {
        "id": pr.player_id,
        "name": pr.name,
        "team": pr.team,
        "division": pr.division,
        "rating": round(pr.rating, 1),
        "played": pr.singles_played,
        "won": pr.singles_won,
        "win_rate": round(pr.win_rate, 4),
        "reliable": pr.reliable,
    }


def _last_played(matches: list[Match]) -> date | None:
    dates = [m.date for m in matches if m.date]
    return max(dates) if dates else None


def build_payload(matches: list[Match]) -> dict:
    """Compute ratings and package everything the front end needs."""
    ratings = calculate_ratings(matches)
    doubles = _doubles_report(matches)
    season = CURRENT_SEASON

    teams = _resolve_teams(matches, ratings, season)

    # A player's division follows their team. Without this, a promoted side
    # would show its new division while its players still showed the old one.
    team_division = {t["name"]: t["division"] for t in teams}
    players = []
    for pr in ratings.values():
        entry = _player_dict(pr)
        entry["division"] = team_division.get(pr.team, pr.division)
        players.append(entry)
    players.sort(key=lambda p: p["rating"], reverse=True)
    carried = [t["name"] for t in teams if t["carried"]]

    last = _last_played(matches)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "season": season_label(season),
        "season_id": season,
        "seasons": sorted({m.season for m in matches}),
        "carried_rosters": len(carried),
        "match_count": len(matches),
        "current_season_matches": sum(1 for m in matches if m.season == season),
        "player_count": len(players),
        "last_match_date": last.isoformat() if last else None,
        "min_matches": MIN_MATCHES,
        "singles_per_match": SINGLES_PER_MATCH,
        "points_per_match": POINTS_PER_MATCH,
        "doubles": doubles,
        "players": players,
        "teams": teams,
    }
