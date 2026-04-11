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

