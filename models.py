from dataclasses import dataclass
from datetime import date


@dataclass
class PlayerResult:
    name: str
    player_id: str  # from URL, e.g. "399203"
    games_won: int  # singles matches won in this team match (0-3)


@dataclass
class TeamResult:
    name: str
    players: list[PlayerResult]
    total_score: int  # total singles wins across team (0-9)


@dataclass
class Match:
    division: int
    date: date | None
    home: TeamResult
    away: TeamResult
    match_id: str = ""  # unique ID from MatchCard URL
    # Seasons run "2025-26", "2026-27". Defaulted so caches written before
    # the app handled more than one season still load.
    season: str = "2025-26"

    @property
    def played(self) -> bool:
        """A match is considered played if any player has a non-zero score, or
        all scores are zero but a total score exists (0-10 result)."""
        all_zero = all(
            p.games_won == 0
            for side in (self.home.players, self.away.players)
            for p in side
        )
        if not all_zero:
            return True
        # A 0-0 result is ambiguous; assume not played if all zeros
        return False


def real_singles(match: Match) -> dict[str, tuple[int, int]]:
    """{player_id: (singles won, singles played)}, walkovers removed.

    A team that turns up short is recorded two different ways, and only one
    of them has to be corrected for. Where the card fills the empty slot with
    a placeholder, the opponents are credited with beating it and a walkover
    sits inside their win count; where the card simply lists two players, it
    does not. Taking a walkover off in both cases removes a win nobody was
    given — Morpeth 8 fielded three against two, won one real single each,
    and were scored nought from two.

    Comparing the wins actually attributed against the singles that could
    really be played tells the two apart: more attributed than playable means
    the walkovers are in there.

    This is the single definition. The rating engine and the per-season
    records both read it, because when they each had their own the two
    drifted apart and the app showed a player a rating and a record that
    disagreed.
    """
    playable = len(match.home.players) * len(match.away.players)
    attributed = sum(
        p.games_won for p in match.home.players + match.away.players
    )
    walkovers_counted = attributed > playable

    singles: dict[str, tuple[int, int]] = {}
    for side, other in ((match.home, match.away), (match.away, match.home)):
        opponents = len(other.players)
        walkovers = (3 - opponents) if walkovers_counted else 0
        for player in side.players:
            singles[player.player_id] = (
                max(0, player.games_won - walkovers),
                opponents,
            )
    return singles
