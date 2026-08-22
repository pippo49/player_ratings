"""Build the JSON payload the web front end runs on.

The front end does all searching, filtering and lineup maths client-side, so
the server only ever has to hand over one document: every rated player, every
team roster, and a little metadata about the data set.
"""

from collections import Counter, defaultdict
from datetime import date, datetime, timezone

from elo import DIVISION_SEED, MIN_MATCHES, PlayerRating, calculate_ratings
from models import Match
from season_transition import DIVISION_OVERRIDES, ROSTER_OVERRIDES, SEASON_LABEL

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


def _apply_season_overrides(
    ratings: dict[str, PlayerRating],
    rosters: dict[str, dict[str, int]],
    divisions: dict[str, int],
) -> None:
    """Apply the next season's known division moves and roster changes.

    Mutates *ratings*, *rosters* and *divisions* in place. Division changes
    come from promotion/relegation and apply to every listed team. Roster
    changes replace a team's squad entirely, only where actually confirmed
    (see season_transition.py) — every other team keeps its 2025/26 roster
    until real 2026/27 results exist.

    A player's `.division` badge always follows their *current* team's new
    division — including players who were not individually overridden but
    whose team was promoted or relegated.
    """
    divisions.update(DIVISION_OVERRIDES)

    for team, roster in ROSTER_OVERRIDES.items():
        new_division = divisions.get(team, 0)
        rosters[team] = {entry["id"]: 0 for entry in roster}
        for entry in roster:
            if entry.get("new"):
                ratings[entry["id"]] = PlayerRating(
                    name=entry["name"],
                    player_id=entry["id"],
                    rating=float(entry.get("rating", DIVISION_SEED[new_division])),
                    division=new_division,
                    team=team,
                )
            else:
                # Carried over from another team (e.g. a lower club side) —
                # keep their rating and stats, just move the label.
                ratings[entry["id"]].team = team

    for pr in ratings.values():
        if pr.team in divisions:
            pr.division = divisions[pr.team]


def build_payload(matches: list[Match]) -> dict:
    """Compute ratings and package everything the front end needs."""
    ratings = calculate_ratings(matches)
    doubles = _doubles_report(matches)
    rosters = _rosters(matches)
    divisions = _team_divisions(matches)
    _apply_season_overrides(ratings, rosters, divisions)

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
        "singles_per_match": SINGLES_PER_MATCH,
        "points_per_match": POINTS_PER_MATCH,
        "doubles": doubles,
        "players": players,
        "teams": teams,
    }
