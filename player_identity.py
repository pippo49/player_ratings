"""Match players across seasons by name, because ids are reissued each year.

The league gives every player a new id each season: of the 178 players
registered for 2026/27, 121 played in 2025/26 and none kept their id. Carrying
ratings by id would therefore seed every returning player from the division
ladder and silently discard a season of history.

Names carry the identity instead. Across 617 players in 2025/26 exactly one
name maps to two ids, so an exact match on a normalised name is safe; anything
short of exact is reported for a human to confirm rather than guessed at, and
confirmed pairs live in data/player_aliases.json.

    .venv/bin/python3 player_identity.py           # review report
"""

import json
import sys
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
ALIASES_FILE = DATA_DIR / "player_aliases.json"

# Below this, two names are unrelated rather than a spelling difference.
NEAR_MATCH_FLOOR = 0.80


def normalise(name: str) -> str:
    """Casefold, strip accents and punctuation, collapse whitespace.

    Handles the differences that are not real: "Debbie O'Neill" against
    "Debbie ONeill", "Jose" against "José", double spaces from a paste.
    """
    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    kept = "".join(c if c.isalnum() or c.isspace() else " " for c in stripped)
    return " ".join(kept.casefold().split())


def load_aliases() -> dict[str, str]:
    """{new season name: previous season name}, as confirmed by a human."""
    if not ALIASES_FILE.exists():
        return {}
    data = json.loads(ALIASES_FILE.read_text())
    return {normalise(k): v for k, v in data.get("aliases", {}).items()}


def build_index(previous: dict) -> tuple[dict, set[str]]:
    """Index previous-season players by normalised name.

    Returns (index, ambiguous). A name held by more than one player is left
    out of the index and reported: guessing which one a returning player is
    would attach someone else's rating to them.
    """
    by_name: dict[str, list] = {}
    for entry in previous.values():
        by_name.setdefault(normalise(entry.name), []).append(entry)

    ambiguous = {name for name, entries in by_name.items() if len(entries) > 1}
    index = {name: entries[0] for name, entries in by_name.items() if len(entries) == 1}
    return index, ambiguous


def find_match(name: str, index: dict, aliases: dict[str, str]):
    """The previous-season player for *name*, or None."""
    key = normalise(name)
    if key in aliases:
        key = normalise(aliases[key])
    return index.get(key)


def near_matches(name: str, index: dict, limit: int = 3) -> list[tuple[float, str]]:
    """Plausible previous-season names for an unmatched player, best first."""
    key = normalise(name)
    scored = []
    for candidate in index:
        # Cheap gate before the expensive comparison.
        if not (set(key.split()) & set(candidate.split())) and abs(
            len(candidate) - len(key)
        ) > 4:
            continue
        ratio = SequenceMatcher(None, key, candidate).ratio()
        if ratio >= NEAR_MATCH_FLOOR:
            scored.append((ratio, index[candidate].name))
    scored.sort(reverse=True)
    return scored[:limit]


def report(season: str = "2026-27") -> int:
    """Print how this season's registered players line up with last season."""
    from cache import load_matches
    from elo import calculate_ratings

    squads_file = DATA_DIR / f"squads_{season}.json"
    if not squads_file.exists():
        print(f"No {squads_file.name} — run fetch_squads.py {season} first.")
        return 1

    previous = calculate_ratings(load_matches())
    index, ambiguous = build_index(previous)
    aliases = load_aliases()

    squads = json.loads(squads_file.read_text())["teams"]
    matched, unmatched = [], []
    for team, info in sorted(squads.items()):
        for player in info["players"]:
            found = find_match(player["name"], index, aliases)
            (matched if found else unmatched).append((team, player["name"], found))

    print(f"{season} squads: {len(matched) + len(unmatched)} players registered")
    print(f"  matched to a 2025/26 rating : {len(matched)}")
    print(f"  no match                    : {len(unmatched)}")
    if ambiguous:
        print(f"  ambiguous last season       : {len(ambiguous)} "
              f"({', '.join(sorted(ambiguous))}) — excluded from matching")

    near, brand_new = [], []
    for team, name, _ in unmatched:
        candidates = near_matches(name, index)
        (near if candidates else brand_new).append((team, name, candidates))

    if near:
        print(f"\n  NEEDS CONFIRMING — {len(near)} close but not exact:")
        for team, name, candidates in near:
            options = ", ".join(f"{n!r} ({r:.0%})" for r, n in candidates)
            print(f"    {name!r} ({team})  ->  {options}")
        print(f"\n  Confirmed pairs go in {ALIASES_FILE.name} as "
              '{"aliases": {"<new name>": "<2025/26 name>"}}')

    if brand_new:
        print(f"\n  New to the league — {len(brand_new)}:")
        for team, name, _ in brand_new[:25]:
            print(f"    {name:28} {team}")
        if len(brand_new) > 25:
            print(f"    … and {len(brand_new) - 25} more")
    return 0


if __name__ == "__main__":
    sys.exit(report(sys.argv[1] if len(sys.argv) > 1 else "2026-27"))
