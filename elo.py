"""ELO rating engine for Central League London table tennis players."""

from collections import Counter
from dataclasses import dataclass
from datetime import date

from models import Match, PlayerResult

# Starting ELO by division: Div 4 = 1500 as baseline, ±100 per division
DIVISION_SEED = {
    1: 1800,
    2: 1700,
    3: 1600,
    4: 1500,
    5: 1400,
    6: 1300,
    7: 1200,
}

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


def _seed_ratings(matches: list[Match]) -> dict[str, PlayerRating]:
    """Build initial ratings seeded by the division each player has played most in."""
    # First pass: count matches per division and per team for each player
    div_counts: dict[str, Counter] = {}   # player_id -> Counter of divisions
    team_counts: dict[str, Counter] = {}  # player_id -> Counter of team names
    names: dict[str, str] = {}

    for match in matches:
        for player in match.home.players:
            names[player.player_id] = player.name
            div_counts.setdefault(player.player_id, Counter())[match.division] += 1
            team_counts.setdefault(player.player_id, Counter())[match.home.name] += 1
        for player in match.away.players:
            names[player.player_id] = player.name
            div_counts.setdefault(player.player_id, Counter())[match.division] += 1
            team_counts.setdefault(player.player_id, Counter())[match.away.name] += 1

    # Build ratings seeded by most-played division
    ratings: dict[str, PlayerRating] = {}
    for pid, name in names.items():
        most_played_div = div_counts[pid].most_common(1)[0][0]
        most_played_team = team_counts[pid].most_common(1)[0][0]
        seed = DIVISION_SEED[most_played_div]
        ratings[pid] = PlayerRating(
            name=name,
            player_id=pid,
            rating=float(seed),
            division=most_played_div,
            team=most_played_team,
        )
    return ratings


def _run_single_pass(
    matches: list[Match],
    ratings: dict[str, PlayerRating],
) -> dict[str, float]:
    """
    Process all matches once, updating ratings in place.

    Stats (matches_played, singles_won, singles_played) are reset at the
    start of each pass so the K-factor decision reflects only matches
    processed so far within this replay — not cumulative across iterations.

    Each player's result is compared against each individual opponent's
    rating. When a team has fewer than 3 players, walkover wins are
    subtracted so only real singles results affect ratings.

    Returns a dict of {player_id: new_rating} so callers can measure convergence.
    """
    for r in ratings.values():
        r.matches_played = 0
        r.singles_won = 0
        r.singles_played = 0

    # Reset ratings to division seed at the start of each full pass so the
    # iterative calculation converges from a clean baseline each time.
    for pr in ratings.values():
        pr.rating = float(DIVISION_SEED[pr.division])

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
            k = K_NEW if pr.matches_played < K_THRESHOLD else K_ESTABLISHED
            pr.rating += k * (actual_frac - expected_frac)

            pr.matches_played += 1
            pr.singles_won += real_wins
            pr.singles_played += n_opponents

        for player in home_players:
            _update(player, away_players)

        for player in away_players:
            _update(player, home_players)

    return {pid: pr.rating for pid, pr in ratings.items()}


def calculate_ratings(matches: list[Match]) -> dict[str, PlayerRating]:
    """
    Compute ELO ratings for all players using iterative convergence.

    Algorithm:
      1. Seed all players with their division's starting rating.
      2. Repeatedly replay all matches, updating ratings each pass.
      3. Stop when the maximum rating change between passes falls below
         CONVERGENCE_THRESHOLD, or after MAX_ITERATIONS.

    The iterative approach compensates for the ordering problem: early
    matches use division seeds, but after several passes the ratings reflect
    actual head-to-head performance across all opponents.
    """
    ratings = _seed_ratings(matches)

    prev_ratings: dict[str, float] = {pid: pr.rating for pid, pr in ratings.items()}

    for _ in range(MAX_ITERATIONS):
        new_ratings = _run_single_pass(matches, ratings)

        max_change = max(
            abs(new_ratings[pid] - prev_ratings.get(pid, DIVISION_SEED.get(ratings[pid].division, 1500)))
            for pid in new_ratings
        )

        prev_ratings = new_ratings.copy()

        if max_change < CONVERGENCE_THRESHOLD:
            break

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
