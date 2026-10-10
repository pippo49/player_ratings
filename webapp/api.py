"""Build the JSON payload the web front end runs on.

The front end does all searching, filtering and lineup maths client-side, so
the server only ever has to hand over one document: every rated player, every
team roster, and a little metadata about the data set.
"""

import json
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

from elo import (
    MIN_MATCHES,
    PlayerRating,
    calculate_ratings,
    canonical_ids,
    seed_for,
)
from models import Match
from scraper import CURRENT_SEASON
from player_identity import (
    DATA_DIR,
    build_index,
    find_match,
    identity,
    load_aliases,
    normalise,
)
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


def _by_team_now(matches: list[Match], of_matches):
    """Apply *of_matches* per team, preferring this season's results.

    A team that has played this season is described by who turned out for it;
    a team that has not is described by last season, which is all there is.
    The choice is per team, not for the league at once: in October a handful
    have played and ninety have not, so scoping everything to the current
    season would empty the app, while pooling the two would list players who
    have left beside players who have joined.
    """
    current = [m for m in matches if m.season == CURRENT_SEASON]
    combined = of_matches(matches)
    combined.update(of_matches(current))
    return combined


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


def _records_by_season(
    matches: list[Match], canonical: dict[str, str]
) -> dict[str, dict[str, dict[str, int]]]:
    """{player_id: {season: {played, won}}}.

    The figures on a player carry their whole career, because that is what the
    rating is built on and what makes it reliable. But a captain picking a side
    wants this season, and wants to compare it against last — a career total of
    sixty singles shows neither. Counted from the matches, since the ratings
    keep no per-season breakdown.

    *canonical* maps each appearance's player id onto the one identity the
    ratings use. Without it last season's records are filed under the numeric
    ids the league has since reissued, and no player matches their own history.
    """
    records: dict[str, dict[str, dict[str, int]]] = {}
    for match in matches:
        for side, other in ((match.home, match.away), (match.away, match.home)):
            # A short opposing side hands out walkovers, which the rating
            # engine discounts; discount them here too so the two agree.
            walkovers = max(0, 3 - len(other.players))
            for player in side.players:
                pid = canonical.get(player.player_id, player.player_id)
                seasons = records.setdefault(pid, {})
                record = seasons.setdefault(match.season, {"played": 0, "won": 0})
                record["played"] += len(other.players)
                record["won"] += max(0, player.games_won - walkovers)
    return records


def _player_dict(
    pr: PlayerRating, by_season: dict[str, dict[str, int]] | None = None
) -> dict:
    season_played = (by_season or {}).get(CURRENT_SEASON, {}).get("played", 0)
    form_delta, form_matches = pr.form()
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
        # Season by season, so the app can show current form against last
        # year's. `played`/`won` above stay career totals, and season_* is
        # kept for the current season because every view uses it.
        "by_season": by_season or {},
        "season_played": season_played,
        "season_won": (by_season or {}).get(CURRENT_SEASON, {}).get("won", 0),
        # Rating movement over the player's last three team matches, and how
        # many it is measured over. The window rolls across the season break:
        # a player one match into the season is measured over that match and
        # the last two of the season before, and the oldest drops off as new
        # ones land. Where the window holds no current-season match at all it
        # is last season's closing form — still their most recent, but the
        # app says so rather than implying it is current.
        "form": round(form_delta, 1),
        "form_matches": form_matches,
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


def load_published_divisions(season: str) -> dict[str, int]:
    """{team: division} as the league published it, from fetch_structure.py.

    This is the authoritative answer for the current season and the only one
    available before a ball is hit. Results can only say which division a
    team played in *last* season, which is wrong the moment anybody is
    promoted or relegated.
    """
    path = DATA_DIR / f"teams_{season}.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    return data.get("teams", data) if isinstance(data, dict) else {}


def load_registered_squads(season: str) -> dict[str, dict]:
    """Squads as registered with the league, from fetch_squads.py.

    Teams register players through the opening weeks of a season, so most
    squads start empty and fill up. An empty one means "not registered yet",
    not "no players", and is left to fall back to last season's roster.
    """
    path = DATA_DIR / f"squads_{season}.json"
    if not path.exists():
        return {}
    teams = json.loads(path.read_text()).get("teams", {})
    return {name: info for name, info in teams.items() if info.get("players")}


def _apply_registered_squads(
    ratings: dict[str, PlayerRating],
    rosters: dict[str, dict[str, int]],
    divisions: dict[str, int],
    squads: dict[str, dict],
) -> set[str]:
    """Replace rosters with the squads actually registered for this season.

    Registered players carry their rating from last season where they played
    it — matched by name, since the league reissues ids each season — and are
    seeded from this season's division ladder where they are new to the
    league. Returns the teams whose squad is real rather than carried.
    """
    name_index, _ = build_index(ratings)
    aliases = load_aliases()
    real: set[str] = set()

    for team, info in squads.items():
        division = divisions.get(team, info.get("division", UNKNOWN_DIVISION))
        divisions[team] = division
        played_for = rosters.get(team, {})
        roster: dict[str, int] = {}

        for player in info["players"]:
            name = player["name"]
            # The shared identity, not the league's id for this season: the
            # ratings are keyed that way (see elo.canonical_ids), and keying a
            # squad entry differently would make one player two rows — a live
            # one from results and a registered one frozen on last season.
            pid = identity(name, aliases)
            rated = ratings.get(pid)

            if rated is not None:
                # Already rated, either from this season's results or carried
                # from last. Either way the rating stands; registering says
                # which team and division they are in now — and how they spell
                # their name, since the identity key is derived from whichever
                # season they first appeared in.
                rated.name = name
                rated.team = team
                rated.division = division
            else:
                previous = find_match(name, name_index, aliases)
                ratings[pid] = PlayerRating(
                    name=name,
                    player_id=pid,
                    rating=previous.rating if previous
                    else seed_for(CURRENT_SEASON, division),
                    division=division,
                    team=team,
                    matches_played=previous.matches_played if previous else 0,
                    singles_won=previous.singles_won if previous else 0,
                    singles_played=previous.singles_played if previous else 0,
                )

            # Appearances this season, where there are any — the front end
            # weights its expected trio by them, so zeroing a player who has
            # already turned out would understate the side.
            roster[pid] = played_for.get(pid, 0)

        rosters[team] = roster
        real.add(team)

    # Anyone whose team now has a registered squad they are not in has left
    # it, and should not show under that team.
    for pr in ratings.values():
        if pr.team in real and pr.player_id not in rosters[pr.team]:
            pr.team = ""
            pr.division = None
    return real


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

    # A roster override replaces a squad outright, so anyone still labelled to
    # that team but missing from the new squad has left it. Without this they
    # keep showing under a team that will not pick them, and count towards
    # that division's stats.
    for pid, pr in ratings.items():
        squad = ROSTER_OVERRIDES.get(pr.team)
        if squad and pid not in {entry["id"] for entry in squad}:
            pr.team = ""
            pr.division = None


def build_payload(matches: list[Match]) -> dict:
    """Compute ratings and package everything the front end needs."""
    ratings = calculate_ratings(matches)
    doubles = _doubles_report(matches)

    projected = not any(m.season == CURRENT_SEASON for m in matches)
    rosters = _by_team_now(matches, _rosters)

    # Divisions inferred from results describe the season those results came
    # from, so last season's promotions and relegations would all be undone.
    # The published structure for this season overrides them where it has an
    # answer, which is for every team the league has entered.
    divisions = _by_team_now(matches, _team_divisions)
    divisions.update(load_published_divisions(CURRENT_SEASON))

    # season_transition.py is a hand-maintained bridge for the gap between
    # seasons. The moment real results exist it is not just unnecessary but
    # wrong, so it stands down on its own rather than waiting to be deleted.
    if projected:
        _apply_season_overrides(ratings, rosters, divisions)

    # The registered squad is who is in the team, and stays the best answer
    # all season: results say how good a player is, not whether they are still
    # in the side, and in October they cover a dozen teams out of ninety. A
    # team that has registered nobody keeps last season's roster, which is the
    # only guide available until it does.
    registered = _apply_registered_squads(
        ratings, rosters, divisions, load_registered_squads(CURRENT_SEASON)
    )

    by_season = _records_by_season(matches, canonical_ids(matches))
    players = sorted(
        (_player_dict(pr, by_season.get(pr.player_id)) for pr in ratings.values()),
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
            # True when this is the squad registered with the league, false
            # when it is last season's roster standing in until they register.
            "registered": team in registered,
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
        "registered_squads": len(registered),
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
