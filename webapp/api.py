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

# A team match is 9 singles plus 1 doubles, so 10 points are on offer.
SINGLES_PER_MATCH = 9
POINTS_PER_MATCH = 10


def _expected(rating: float, opponent: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((opponent - rating) / 400.0))


def _pair_rating(ratings: dict[str, PlayerRating], players) -> float | None:
    """Doubles strength of a side, modelled as the mean of its top two singles ratings."""
    known = sorted(
        (ratings[p.player_id].rating for p in players if p.player_id in ratings),
        reverse=True,
    )
    if len(known) < 2:
        return None
    return sum(known[:2]) / 2


def _doubles_report(matches: list[Match], ratings: dict[str, PlayerRating]) -> dict:
    """Check that the doubles point can be recovered, and how well the model predicts it.

    The scraped data gives each player's singles wins and the team's total. The
    doubles point is whatever is left over, so it should always be 0 or 1. Any
    other value means the assumption does not hold for that match and the
    doubles model should not be trusted.
    """
    recovered = anomalies = home_wins = correct = 0
    brier = 0.0
    scored = 0

    for match in matches:
        home_singles = sum(p.games_won for p in match.home.players)
        away_singles = sum(p.games_won for p in match.away.players)
        home_point = match.home.total_score - home_singles
        away_point = match.away.total_score - away_singles

        if {home_point, away_point} != {0, 1}:
            anomalies += 1
            continue
        recovered += 1
        home_won = home_point == 1
        home_wins += home_won

        home_pair = _pair_rating(ratings, match.home.players)
        away_pair = _pair_rating(ratings, match.away.players)
        if home_pair is None or away_pair is None:
            continue
        predicted = _expected(home_pair, away_pair)
        brier += (predicted - float(home_won)) ** 2
        correct += (predicted >= 0.5) == home_won
        scored += 1

    return {
        "matches": len(matches),
        "recovered": recovered,
        "anomalies": anomalies,
        "home_win_rate": round(home_wins / recovered, 4) if recovered else None,
        "model_scored": scored,
        "model_accuracy": round(correct / scored, 4) if scored else None,
        "model_brier": round(brier / scored, 4) if scored else None,
        "trustworthy": bool(recovered) and anomalies / max(len(matches), 1) < 0.02,
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


def build_payload(matches: list[Match]) -> dict:
    """Compute ratings and package everything the front end needs."""
    ratings = calculate_ratings(matches)
    doubles = _doubles_report(matches, ratings)
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
        "singles_per_match": SINGLES_PER_MATCH,
        "points_per_match": POINTS_PER_MATCH,
        "doubles": doubles,
        "players": players,
        "teams": teams,
    }
