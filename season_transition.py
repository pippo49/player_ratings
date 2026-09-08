"""Static overrides for moving from Winter 2025/26 into Winter 2026/27.

The division map is now the published one, fetched by fetch_structure.py into
data/teams_2026-27.json. The inferred promotion/relegation map below is kept
only as a fallback, and it was wrong: it relegated Apex 4 to Division 5 where
the league in fact kept them in Division 4.


The 2025/26 season is finished and 2026/27 fixtures are not published yet, so
there is no new match data to scrape (see NEXT_SEASON.md). Until then, the
app shows a preseason projection: 2025/26 ratings carried over unchanged as
each player's starting point — nobody is reseeded just for moving division —
plus the division and roster changes already known.

Division changes come from the official Winter 2025/26 final tables
(tabletennis365.com/CentralLondon/Tables/Winter_2025-26/<Division>): the top
2 teams in each division are promoted (Division 1 has nowhere to go) and the
bottom 2 are relegated (Division 7 has nowhere to go). Every other team is
assumed unchanged — including its roster — until the league publishes real
2026/27 results.

Roster changes are only applied where actually known. Right now that is just
Apex 4, whose 2026/27 squad is confirmed.
"""

import json
from pathlib import Path

SEASON_LABEL = "Winter 2026/27"
SEASON = "2026-27"

_DATA_DIR = Path(__file__).resolve().parent / "data"

# A player who turned out more than this many times for a club-mate team in
# a higher division (lower division number) than another team they also
# played for is assumed to play for that higher team next season — a
# frequent call-up reads as a promotion, not a one-off fill-in. Applies
# automatically to every team, not just the ones in ROSTER_OVERRIDES below.
CALL_UP_PROMOTION_THRESHOLD = 4

def _published_divisions() -> dict[str, int]:
    """The real {team: division} map for the season, if it has been fetched.

    Written by fetch_structure.py from the league's own pages. It supersedes
    the inferred map below entirely — the league does not always follow
    promotion and relegation exactly, as withdrawals, mergers and new teams
    all move sides around.
    """
    path = _DATA_DIR / f"teams_{SEASON}.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    return {name: int(division) for name, division in data.get("teams", {}).items()}


# {team_name: new_division}, inferred from the Winter 2025/26 final tables by
# applying promotion and relegation. A fallback: superseded the moment
# fetch_structure.py has written the published structure.
_INFERRED_DIVISIONS = {
    "Morpeth 6": 2,
    "Morpeth 5": 2,
    "Flick TTC 1": 1,
    "Table Tennis Fight Club 1": 1,
    "St Katharines Trust 4": 3,
    "Morpeth 8": 3,
    "Fusion 4": 2,
    "Fulham Brunswick 2": 2,
    "Moberly 3": 4,
    "Apex 3": 4,
    "Flick TTC 2": 3,
    "Fusion 5": 3,
    "St Katharines Trust 6": 5,
    "Apex 4": 5,
    "Fusion 7": 4,
    "St Katharines Trust 7": 4,
    "Highbury 5": 6,
    "Morpeth 12 Jr": 6,
    "TJ TTC 2": 5,
    "Clissold 4": 5,
    "Highbury 6": 7,
    "Highbury 7": 7,
    "Fusion 10 Jr": 6,
    "Flick TTC 4": 6,
}

# The published structure wins where it exists.
DIVISION_OVERRIDES = _published_divisions() or _INFERRED_DIVISIONS
DIVISIONS_ARE_PUBLISHED = bool(_published_divisions())

# {team_name: [player entries]}. A listed team's roster is replaced entirely
# (not merged with its 2025/26 roster). Each entry is either:
#   {"id": "<existing player_id>"}                                    — carries over rating
#   {"id": "<synthetic id>", "name": "...", "new": True, "rating": n}  — no rating history,
#     starts at the given rating (falls back to the division seed if omitted)
ROSTER_OVERRIDES = {
    "Apex 4": [
        {"id": "399437"},  # Philip Parsons
        {"id": "399515"},  # Alex Pillen
        {"id": "399439"},  # Alina Binte Rashad
        {"id": "400328"},  # Sophia Nallalingham
        {"id": "400324"},  # Luca Pagnanelli
        {"id": "401772"},  # Ziye Ke
        {"id": "400325"},  # Peter Dunmow
        {"id": "new-srini-apex4", "name": "Srini", "new": True, "rating": 1450},
        {"id": "new-ash-apex4", "name": "Ash", "new": True, "rating": 1400},
    ],
}
