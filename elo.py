"""ELO rating engine for Central League London table tennis players."""

import json
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import date

from models import Match, PlayerResult, TeamResult
from player_identity import (
    DATA_DIR,
    build_index,
    find_match,
    identity,
    load_aliases,
    normalise,
)

# Starting ELO by division, for a player with no rating history. Only ever
# applies to someone genuinely new — anyone with a previous season carries
# their rating forward instead.
#
# The ladder is season-specific because the league restructured for 2026/27,
# adding a Premier division above Divisions One to Seven. A division number
# no longer means what it meant in 2025/26, so seeding a 2026/27 newcomer
# from the 2025/26 ladder would start them about 90 points high — which does
# not just mislabel them, it leaks into everyone else's rating, since beating
# an over-rated opponent pays out too much.
#
# 2025/26: seven tiers, Div 4 at 1500 as the midpoint, 100 per division.
# Median players finished within 21 points of their seed, so it is left alone
# — changing it would move every existing rating.
SEASON_2025_26_SEED = {
    1: 1800,
    2: 1700,
    3: 1600,
    4: 1500,
    5: 1400,
    6: 1300,
    7: 1200,
}

# 2026/27: eight tiers. Anchored at 1850 for the Premier, still 100 apart.
# Fitted to the median rating of the players actually placed in each
# division, which gives a mean error of 30 points against 98 for carrying the
# old ladder up a division.
SEASON_2026_27_SEED = {
    0: 1850,  # Premier
    1: 1750,
    2: 1650,
    3: 1550,
    4: 1450,
    5: 1350,
    6: 1250,
    7: 1150,
}

SEASON_SEEDS = {
    "2025-26": SEASON_2025_26_SEED,
    "2026-27": SEASON_2026_27_SEED,
}

# A season with no ladder of its own uses the most recent one defined.
LATEST_SEED_LADDER = SEASON_SEEDS[max(SEASON_SEEDS)]


def seed_for(season: str, division: int) -> float:
    """The starting rating for a new player in *division* during *season*.

    Falls back to the newest ladder for an unknown season, and to the nearest
    division within that ladder for a division it does not list — a new tier
    should not raise KeyError mid-season.
    """
    ladder = SEASON_SEEDS.get(season, LATEST_SEED_LADDER)
    if division in ladder:
        return float(ladder[division])
    nearest = min(ladder, key=lambda d: abs(d - division))
    return float(ladder[nearest])

K_NEW = 48       # K-factor for players with < K_THRESHOLD team matches (converge faster)
K_ESTABLISHED = 32  # K-factor for players with >= K_THRESHOLD team matches
K_THRESHOLD = 15    # team matches before switching to the lower K-factor

# A carried rating is a stale prior. Months pass over the summer, players
# improve or fall away, and nothing in last season's results knows about it —
# so the start of a season is treated as provisional again, whatever a
# player's career record says. For their first few team matches of a season
# they move on the high K, then settle onto the low one.
#
# Six is about the first quarter of a twenty-match season: long enough for a
# real change in standard to show, short enough that one freak night cannot
# define someone's year. Raising it buys responsiveness and pays in noise.
K_SEASON_SETTLE = 6
CONVERGENCE_THRESHOLD = 0.5  # max rating change per iteration to declare convergence
MAX_ITERATIONS = 20
MIN_MATCHES = 15  # minimum singles matches before a rating is considered reliable


@dataclass
class PlayerRating:
    name: str
    player_id: str
    rating: float
    division: int            # division the player has played most matches in
    team: str = ""           # team the player has played most matches for
    matches_played: int = 0
    singles_won: int = 0       # total singles matches won
    singles_played: int = 0   # total singles matches played (3 per team match)
    # The rating after each team match, starting with the seed the player's
    # first season began on. Recorded on every convergence pass and reset at
    # the start of each, so what survives is the final pass; seasons are then
    # joined end to end, since each is seeded from the last one's close.
    trail: list[float] = field(default_factory=list)

    def form(self, over: int = 3) -> tuple[float, int]:
        """Rating change across the last *over* team matches, and how many.

        Opponent ratings are held at their converged values through the final
        pass, so this is what the player's own recent results moved them by,
        not an artefact of everyone else moving at the same time.

        The trail runs across season boundaries, so three matches into a new
        season still reaches back into the last one rather than reporting form
        over a single night. A player with fewer matches than asked for gets
        the change across all of them, and the count says so.
        """
        if len(self.trail) < 2:
            return 0.0, 0
        played = min(over, len(self.trail) - 1)
        return self.trail[-1] - self.trail[-1 - played], played

    @property
    def reliable(self) -> bool:
        return self.singles_played >= MIN_MATCHES

    @property
    def win_rate(self) -> float:
        if self.singles_played == 0:
            return 0.0
        return self.singles_won / self.singles_played


def _expected_score(rating: float, opponent_rating: float) -> float:
    """Standard ELO expected score in range [0, 1]."""
    return 1.0 / (1.0 + 10.0 ** ((opponent_rating - rating) / 400.0))


def load_registered_divisions(season: str) -> dict[str, int]:
    """{normalised player name: the division of the team they registered for}.

    A player called up to a higher team plays in that team's division, so a
    division inferred from appearances describes the match, not the player.
    Seeded that way, a Division 5 player borrowed by a Division 2 side starts
    from the Division 2 ladder: lose all three and you still come out rated
    far above a teammate who never played. The registration says which level
    they actually belong to.
    """
    path = DATA_DIR / f"squads_{season}.json"
    if not path.exists():
        return {}
    teams = json.loads(path.read_text()).get("teams", {})
    divisions: dict[str, int] = {}
    for info in teams.values():
        division = info.get("division")
        if division is None:
            continue
        for player in info.get("players", []):
            divisions.setdefault(normalise(player["name"]), division)
    return divisions


def _seed_ratings(
    matches: list[Match],
    season: str,
    carried: dict[str, PlayerRating] | None = None,
) -> dict[str, PlayerRating]:
    """Build starting ratings for the players appearing in *matches*.

    A player carried over from a previous season starts from the rating they
    finished it on. Anyone new starts from the seed for the division of the
    team they registered with, falling back to the division they played most
    in when they are not registered anywhere. Team and division labels are
    taken from *these* matches, so they reflect the season being rated rather
    than a player's history.

    Carried players are found by id first and by name second, because the
    league reissues player ids every season — matching on id alone would
    treat every returning player as new and throw away their rating.
    """
    carried = carried or {}
    name_index, _ambiguous = build_index(carried)
    aliases = load_aliases()
    registered_division = load_registered_divisions(season)

    # First pass: count matches per division and per team for each player
    div_counts: dict[str, Counter] = {}   # player_id -> Counter of divisions
    team_counts: dict[str, Counter] = {}  # player_id -> Counter of team names
    names: dict[str, str] = {}

    for match in matches:
        for side in (match.home, match.away):
            for player in side.players:
                names[player.player_id] = player.name
                div_counts.setdefault(player.player_id, Counter())[match.division] += 1
                team_counts.setdefault(player.player_id, Counter())[side.name] += 1

    ratings: dict[str, PlayerRating] = {}
    for pid, name in names.items():
        most_played_div = div_counts[pid].most_common(1)[0][0]
        most_played_team = team_counts[pid].most_common(1)[0][0]
        previous = carried.get(pid) or find_match(name, name_index, aliases)
        own_div = registered_division.get(normalise(name), most_played_div)
        seed = previous.rating if previous else seed_for(season, own_div)
        ratings[pid] = PlayerRating(
            name=name,
            player_id=pid,
            rating=seed,
            division=most_played_div,
            team=most_played_team,
        )
    return ratings


def _run_single_pass(
    matches: list[Match],
    ratings: dict[str, PlayerRating],
    seeds: dict[str, float],
    experience: dict[str, int],
) -> dict[str, float]:
    """
    Process all matches once, updating ratings in place.

    Stats (matches_played, singles_won, singles_played) are reset at the
    start of each pass so the K-factor decision reflects only matches
    processed so far within this replay — not cumulative across iterations.
    *experience* carries a player's team matches from previous seasons, so
    someone already established does not go back to the high K-factor.

    Ratings are reset to *seeds* rather than to the division baseline, which
    is what lets a season start from the previous season's final ratings.

    Each player's result is compared against each individual opponent's
    rating. When a team has fewer than 3 players, walkover wins are
    subtracted so only real singles results affect ratings.

    Returns a dict of {player_id: new_rating} so callers can measure convergence.
    """
    for pid, r in ratings.items():
        r.matches_played = 0
        r.singles_won = 0
        r.singles_played = 0
        r.rating = seeds[pid]
        r.trail = [seeds[pid]]

    # Replay matches in chronological order so the final pass gives
    # temporally-ordered ratings (latest form matters most).
    sorted_matches = sorted(matches, key=lambda m: m.date or date.min)

    for match in sorted_matches:
        home_players = match.home.players
        away_players = match.away.players

        if not all(p.player_id in ratings for p in home_players + away_players):
            continue

        def _update(player: PlayerResult, opponents: list[PlayerResult]) -> None:
            pr = ratings[player.player_id]
            n_opponents = len(opponents)

            # When the opposing team is short (2 players instead of 3),
            # the player's shown score includes walkover wins.
            # Subtract those to get real performance only.
            walkovers = 3 - n_opponents
            real_wins = max(0, player.games_won - walkovers)

            # Compare against each real opponent individually so that
            # beating a stronger player counts for more.
            total_expected = sum(
                _expected_score(pr.rating, ratings[opp.player_id].rating)
                for opp in opponents
            )
            actual_frac = real_wins / n_opponents
            expected_frac = total_expected / n_opponents
            # matches_played is reset each pass, so it counts this season's
            # matches already processed — the ones before this one.
            this_season = pr.matches_played
            career = experience.get(player.player_id, 0) + this_season
            k = (
                K_NEW
                if this_season < K_SEASON_SETTLE or career < K_THRESHOLD
                else K_ESTABLISHED
            )
            pr.rating += k * (actual_frac - expected_frac)

            pr.matches_played += 1
            pr.singles_won += real_wins
            pr.singles_played += n_opponents
            pr.trail.append(pr.rating)

        for player in home_players:
            _update(player, away_players)

        for player in away_players:
            _update(player, home_players)

    return {pid: pr.rating for pid, pr in ratings.items()}


def _rate_season(
    matches: list[Match],
    season: str,
    carried: dict[str, PlayerRating],
) -> dict[str, PlayerRating]:
    """Converge ratings over one season's matches, starting from *carried*."""
    ratings = _seed_ratings(matches, season, carried)
    seeds = {pid: pr.rating for pid, pr in ratings.items()}
    # Same identity rule as the seed: id first, then name.
    name_index, _ = build_index(carried)
    aliases = load_aliases()
    previous_of: dict[str, PlayerRating] = {}
    for pid, pr in ratings.items():
        found = carried.get(pid) or find_match(pr.name, name_index, aliases)
        if found is not None:
            previous_of[pid] = found
    experience = {pid: prev.matches_played for pid, prev in previous_of.items()}

    prev_ratings = dict(seeds)
    for _ in range(MAX_ITERATIONS):
        new_ratings = _run_single_pass(matches, ratings, seeds, experience)
        max_change = max(
            abs(new_ratings[pid] - prev_ratings[pid]) for pid in new_ratings
        )
        prev_ratings = new_ratings.copy()
        if max_change < CONVERGENCE_THRESHOLD:
            break

    # Match counts are a career total, so a player's rating stays "reliable"
    # across a season boundary rather than resetting to provisional.
    for pid, pr in ratings.items():
        previous = previous_of.get(pid)
        if previous:
            pr.matches_played += previous.matches_played
            pr.singles_won += previous.singles_won
            pr.singles_played += previous.singles_played
            # Join the trails so form can look back past the season boundary.
            # A season is seeded from the rating the previous one ended on, so
            # the two meet at the same value: drop the duplicate join point.
            pr.trail = previous.trail[:-1] + pr.trail
    return ratings


def canonical_ids(matches: list[Match]) -> dict[str, str]:
    """{player_id: the id to rate that player under}.

    The league reissues numeric player ids every season, so an id identifies
    an appearance, not a person — and the 2026/27 match cards carry no id at
    all, so parser_v2 uses the normalised name. Left alone, a returning player
    is two people: a numeric id frozen on last season's results and a
    name-keyed one carrying this season's.

    So the name is the identity, and ids map onto it. A player who registered
    under a different name is folded in through the confirmed alias list, or
    their two seasons would sit under two keys and neither would hold their
    whole record.

    The exception is a name two different players share within one season —
    there the ids are the only thing telling them apart, and collapsing by
    name would merge two people, so those keep their own ids.
    """
    aliases = load_aliases()
    per_season: dict[str, dict[str, set[str]]] = {}
    for match in matches:
        names = per_season.setdefault(match.season, {})
        for side in (match.home, match.away):
            for player in side.players:
                names.setdefault(identity(player.name, aliases), set()).add(player.player_id)

    shared = {
        name
        for names in per_season.values()
        for name, ids in names.items()
        if len(ids) > 1
    }

    canonical: dict[str, str] = {}
    for names in per_season.values():
        for name, ids in names.items():
            if name in shared:
                continue
            for pid in ids:
                canonical[pid] = name
    return canonical


def _with_canonical_ids(matches: list[Match]) -> list[Match]:
    """The same matches, with every player id resolved to one identity."""
    canonical = canonical_ids(matches)
    if all(canonical.get(pid, pid) == pid for pid in canonical):
        return matches

    def side(team: TeamResult) -> TeamResult:
        return replace(team, players=[
            replace(p, player_id=canonical.get(p.player_id, p.player_id))
            for p in team.players
        ])

    return [replace(m, home=side(m.home), away=side(m.away)) for m in matches]


def calculate_ratings(matches: list[Match]) -> dict[str, PlayerRating]:
    """
    Compute ELO ratings for all players, season by season.

    Each season is converged on its own, seeded from the ratings players
    finished the previous season on. That keeps last season's standings as
    the starting point while letting new results move them, rather than
    replaying every season from division seeds each time — which would give
    old results permanent weight and let a promotion retroactively rewrite a
    player's history.

    Within a season the algorithm is:
      1. Seed each player from their carried-over rating, or their
         division's starting rating if they are new.
      1a. Treat everyone as provisional for their first K_SEASON_SETTLE team
         matches of the season, so a summer's change in standard shows up
         rather than being held back by a rating built before it.
      2. Repeatedly replay the season's matches, updating ratings each pass.
      3. Stop when the maximum rating change between passes falls below
         CONVERGENCE_THRESHOLD, or after MAX_ITERATIONS.

    Players who do not appear in a later season keep the rating, team and
    division they finished their last one on.
    """
    # One identity per player before anything is rated, so a returning player
    # is not split between a numeric id and a name.
    matches = _with_canonical_ids(matches)

    seasons = sorted({m.season for m in matches})
    ratings: dict[str, PlayerRating] = {}

    for season in seasons:
        season_matches = [m for m in matches if m.season == season]
        if not season_matches:
            continue
        # Players who sat the season out keep their existing entry.
        ratings = {**ratings, **_rate_season(season_matches, season, ratings)}

    return ratings


def top_players(
    ratings: dict[str, PlayerRating],
    division: int | None = None,
    min_matches: int = MIN_MATCHES,
    n: int = 20,
) -> list[PlayerRating]:
    """Return the top N players sorted by rating, optionally filtered by division."""
    players = [
        pr for pr in ratings.values()
        if pr.singles_played >= min_matches
        and (division is None or pr.division == division)
    ]
    return sorted(players, key=lambda pr: pr.rating, reverse=True)[:n]


def lookup_player(ratings: dict[str, PlayerRating], name_fragment: str) -> list[PlayerRating]:
    """Find players whose name contains the given fragment (case-insensitive)."""
    fragment = name_fragment.lower()
    return sorted(
        [pr for pr in ratings.values() if fragment in pr.name.lower()],
        key=lambda pr: pr.rating,
        reverse=True,
    )


def lookup_team(ratings: dict[str, PlayerRating], team_fragment: str) -> list[PlayerRating]:
    """Find all players whose team name contains the given fragment (case-insensitive)."""
    fragment = team_fragment.lower()
    return sorted(
        [pr for pr in ratings.values() if fragment in pr.team.lower()],
        key=lambda pr: pr.rating,
        reverse=True,
    )
