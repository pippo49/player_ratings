"""ELO rating engine for Central League London table tennis players."""

from collections import Counter
from dataclasses import dataclass
from datetime import date

from models import Match, PlayerResult

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


def _seed_ratings(
    matches: list[Match],
    season: str,
    carried: dict[str, PlayerRating] | None = None,
) -> dict[str, PlayerRating]:
    """Build starting ratings for the players appearing in *matches*.

    A player carried over from a previous season starts from the rating they
    finished it on. Anyone new starts from the seed for the division they
    play most in. Team and division are always taken from *these* matches,
    so labels reflect the season being rated rather than a player's history.
    """
    carried = carried or {}

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
        previous = carried.get(pid)
        seed = previous.rating if previous else seed_for(season, most_played_div)
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
            played = experience.get(player.player_id, 0) + pr.matches_played
            k = K_NEW if played < K_THRESHOLD else K_ESTABLISHED
            pr.rating += k * (actual_frac - expected_frac)

            pr.matches_played += 1
            pr.singles_won += real_wins
            pr.singles_played += n_opponents

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
    experience = {
        pid: carried[pid].matches_played for pid in ratings if pid in carried
    }

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
        previous = carried.get(pid)
        if previous:
            pr.matches_played += previous.matches_played
            pr.singles_won += previous.singles_won
            pr.singles_played += previous.singles_played
    return ratings


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
      2. Repeatedly replay the season's matches, updating ratings each pass.
      3. Stop when the maximum rating change between passes falls below
         CONVERGENCE_THRESHOLD, or after MAX_ITERATIONS.

    Players who do not appear in a later season keep the rating, team and
    division they finished their last one on.
    """
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
