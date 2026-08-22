"""Build the JSON payload the web front end runs on.

The front end does all searching, filtering and lineup maths client-side, so
the server only ever has to hand over one document: every rated player, every
team roster, and a little metadata about the data set.
"""

from collections import Counter, defaultdict
from datetime import date, datetime, timezone

from elo import MIN_MATCHES, PlayerRating, calculate_ratings
from models import Match

SEASON_LABEL = "Winter 2025/26"


def _rosters(matches: list[Match]) -> dict[str, dict[str, int]]:
    """Return {team_name: {player_id: appearances}} across all matches.

    A player can turn out for more than one team over a season, so rosters are
    built from the matches themselves rather than from each player's single
    "most played for" team.
    """
    rosters: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for match in matches:
        for side in (match.home, match.away):
            for player in side.players:
                rosters[side.name][player.player_id] += 1
    return {team: dict(players) for team, players in rosters.items()}


def _team_divisions(matches: list[Match]) -> dict[str, int]:
    """Return {team_name: division it has played most matches in}."""
    counts: dict[str, Counter] = defaultdict(Counter)
    for match in matches:
        counts[match.home.name][match.division] += 1
        counts[match.away.name][match.division] += 1
    return {team: c.most_common(1)[0][0] for team, c in counts.items()}


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
    rosters = _rosters(matches)
    divisions = _team_divisions(matches)

    players = sorted(
        (_player_dict(pr) for pr in ratings.values()),
        key=lambda p: p["rating"],
        reverse=True,
    )

    teams = []
    for team, roster in sorted(rosters.items()):
        member_ids = [pid for pid in roster if pid in ratings]
        if not member_ids:
            continue
        member_ids.sort(key=lambda pid: ratings[pid].rating, reverse=True)
        teams.append({
            "name": team,
            "division": divisions.get(team, 0),
            "players": [
                {"id": pid, "appearances": roster[pid]}
                for pid in member_ids
            ],
        })

    last = _last_played(matches)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "season": SEASON_LABEL,
        "match_count": len(matches),
        "player_count": len(players),
        "last_match_date": last.isoformat() if last else None,
        "min_matches": MIN_MATCHES,
        "players": players,
        "teams": teams,
    }
