"""Build the JSON payload the web front end runs on.

The front end does all searching, filtering and lineup maths client-side, so
the server only ever has to hand over one document: every rated player, every
team roster, and a little metadata about the data set.
"""

from collections import Counter, defaultdict
from datetime import date, datetime, timezone

from elo import MIN_MATCHES, PlayerRating, calculate_ratings, seed_for
from models import Match
from scraper import CURRENT_SEASON
from season_transition import (
    CALL_UP_PROMOTION_THRESHOLD,
    DIVISION_OVERRIDES,
    DIVISIONS_ARE_PUBLISHED,
    ROSTER_OVERRIDES,
    SEASON_LABEL,
)

# Where a team's division genuinely is not known. Mid-table rather than 0,
# which from 2026/27 means the Premier.
UNKNOWN_DIVISION = 4

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


def _relevant_matches(matches: list[Match]) -> list[Match]:
    """The matches that describe who plays where *now*.

    Once the current season has results of its own they are the only honest
    answer, and pooling them with last season's would list players who have
    left alongside players who have joined. Before then — the usual state in
    September — last season's matches are all there is.
    """
    current = [m for m in matches if m.season == CURRENT_SEASON]
    return current or matches


def _rosters(matches: list[Match]) -> dict[str, dict[str, int]]:
    """Return {team_name: {player_id: appearances}} across *matches*.

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


def _infer_call_up_promotions(
    rosters: dict[str, dict[str, int]],
    divisions: dict[str, int],
) -> dict[str, str]:
    """{player_id: team} for players assumed to move up to a higher-division
    club-mate team next season, based on frequent call-ups last season.

    A player qualifies for a team if they made more than
    CALL_UP_PROMOTION_THRESHOLD appearances for it. Among the teams they
    qualify for, the highest division (lowest division number) wins — so a
    player who mostly played for their own lower side but was called up
    often enough to a higher one is assumed promoted, even though the lower
    side has more total appearances.
    """
    qualifying: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for team, roster in rosters.items():
        division = divisions.get(team)
        if division is None:
            continue
        for pid, appearances in roster.items():
            if appearances > CALL_UP_PROMOTION_THRESHOLD:
                qualifying[pid].append((division, team))

    return {pid: min(teams)[1] for pid, teams in qualifying.items()}


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
    whose team was promoted or relegated. Each player ends up on exactly one
    team's projected roster — their final `.team` — even if the 2025/26 data
    has them turning out for others too, so a club-mate team they are no
    longer expected to play for does not still list them as available.
    """
    # Frequent-call-up inference uses last season's divisions (who counts as
    # "higher" is a 2025/26 question), before promotion/relegation moves the
    # teams themselves for next season.
    promotions = _infer_call_up_promotions(rosters, divisions)
    for pid, team in promotions.items():
        if pid in ratings:
            ratings[pid].team = team

    divisions.update(DIVISION_OVERRIDES)

    # A published structure is the whole league, so a team missing from it has
    # withdrawn or merged. Drop it, rather than leaving it in last season's
    # division to distort the table it is no longer part of.
    if DIVISIONS_ARE_PUBLISHED:
        for team in [t for t in rosters if t not in DIVISION_OVERRIDES]:
            del rosters[team]
            divisions.pop(team, None)

    for team, roster in ROSTER_OVERRIDES.items():
        # Division 0 is the Premier from 2026/27, so it cannot double as an
        # "unknown" fallback — that would seed a new player at Premier level.
        new_division = divisions.get(team, UNKNOWN_DIVISION)
        rosters[team] = {entry["id"]: 0 for entry in roster}
        for entry in roster:
            if entry.get("new"):
                ratings[entry["id"]] = PlayerRating(
                    name=entry["name"],
                    player_id=entry["id"],
                    rating=float(entry.get("rating", seed_for(CURRENT_SEASON, new_division))),
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

    # A player belongs to one projected team next season. Drop them from
    # every other team's roster so a club-mate side they used to be called
    # up for does not still list them as an available player.
    for pid, pr in ratings.items():
        for team, roster in rosters.items():
            if team != pr.team:
                roster.pop(pid, None)


def build_payload(matches: list[Match]) -> dict:
    """Compute ratings and package everything the front end needs."""
    ratings = calculate_ratings(matches)
    doubles = _doubles_report(matches)

    # Scope rosters and divisions to the current season once it has results.
    current = _relevant_matches(matches)
    projected = not any(m.season == CURRENT_SEASON for m in matches)
    rosters = _rosters(current)
    divisions = _team_divisions(current)

    # season_transition.py is a hand-maintained bridge for the gap between
    # seasons. The moment real results exist it is not just unnecessary but
    # wrong, so it stands down on its own rather than waiting to be deleted.
    if projected:
        _apply_season_overrides(ratings, rosters, divisions)

    players = sorted(
        (_player_dict(pr) for pr in ratings.values()),
        key=lambda p: p["rating"],
        reverse=True,
    )

    teams = []
    for team, roster in sorted(rosters.items()):
        member_ids = [pid for pid in roster if pid in ratings]
        division = divisions.get(team)
        # A team of no known division cannot be placed, and defaulting it to 0
        # would file it under the Premier.
        if not member_ids or division is None:
            continue
        member_ids.sort(key=lambda pid: ratings[pid].rating, reverse=True)
        teams.append({
            "name": team,
            "division": division,
            "players": [
                {"id": pid, "appearances": roster[pid]}
                for pid in member_ids
            ],
        })

    last = _last_played(matches)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "season": SEASON_LABEL,
        "season_id": CURRENT_SEASON,
        # True while the new season has no results and the app is showing a
        # projection built from last season's ratings and known moves.
        "projected": projected,
        "seasons": sorted({m.season for m in matches}),
        "match_count": len(matches),
        "current_season_matches": sum(1 for m in matches if m.season == CURRENT_SEASON),
        "player_count": len(players),
        "last_match_date": last.isoformat() if last else None,
        "min_matches": MIN_MATCHES,
        "singles_per_match": SINGLES_PER_MATCH,
        "points_per_match": POINTS_PER_MATCH,
        "doubles": doubles,
        "players": players,
        "teams": teams,
    }
