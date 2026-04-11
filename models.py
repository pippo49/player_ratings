from dataclasses import dataclass, field
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

    def player_fractional_score(self, player: PlayerResult) -> float:
        """Return a player's result as a fraction of singles matches won (0.0–1.0)."""
        return player.games_won / 3.0

    def opposing_players(self, player: PlayerResult) -> list[PlayerResult]:
        """Return the 3 opposing players for a given player."""
        if player in self.home.players:
            return self.away.players
        return self.home.players
