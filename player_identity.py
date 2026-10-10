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

# A player registered to the same club in both seasons is far more likely to
# be the same person, so a weaker resemblance is still worth a human's look.
# "Dave" against "David", a married name, a transliteration — all score below
# the general floor and all turn up at the same club.
SAME_CLUB_FLOOR = 0.62


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


def load_non_matches() -> dict[str, set[str]]:
    """{new season name: previous names confirmed to be someone else}.

    Squads are re-scraped through the season, so without this the same
    rejected suggestion would come back for review every single time.

    A name can be offered more than one candidate — Fusion have three
    Dennisons — so a value may be a single name or a list of them.
    """
    if not ALIASES_FILE.exists():
        return {}
    data = json.loads(ALIASES_FILE.read_text())
    rejected: dict[str, set[str]] = {}
    for key, value in data.get("not_matches", {}).items():
        names = [value] if isinstance(value, str) else value
        rejected.setdefault(normalise(key), set()).update(
            normalise(n) for n in names
        )
    return rejected


def identity(name: str, aliases: dict[str, str] | None = None) -> str:
    """The single key a player is known by, with confirmed renames folded in.

    normalise() alone is not an identity: a player who re-registered under a
    different name normalises to two different keys, so their seasons sit
    apart and whichever half a caller happens to key on is the half it sees.
    Everything that identifies a player — the rating engine, the squad loader,
    the per-season records — must agree, so they all come through here.
    """
    aliases = load_aliases() if aliases is None else aliases
    key = normalise(name)
    return normalise(aliases[key]) if key in aliases else key


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


def club(team: str) -> str:
    """The club a team belongs to: "Apex 4" and "Apex 5" are both "apex".

    Teams are numbered per club, with "Jr" on the junior sides, so stripping
    the trailing number leaves the club. Used to tell whether a player has
    stayed put between seasons.
    """
    words = normalise(team).split()
    while words and (words[-1].isdigit() or words[-1] == "jr"):
        words.pop()
    return " ".join(words)


def _initials(words: list[str]) -> str:
    return "".join(w[0] for w in words if w)


def same_person_by_initials(name: str, candidate: str) -> bool:
    """Whether two names are the same surname and consistent forenames.

    "Cp Sahu" and "Chandra Prakash Sahu" are one player registered twice, once
    under his initials. String similarity scores that pair at 0.52 — nowhere
    near the floor — because initials share almost no characters with the
    names they stand for. Comparing them as initials instead is exact.

    The abbreviated side has to genuinely be initials: either every forename
    is a single letter, or one token spells out the other side's initials.
    Settling for "shorter than" would match "John Smith" to "James Smith" on
    the strength of a shared J.
    """
    mine, theirs = normalise(name).split(), normalise(candidate).split()
    if len(mine) < 2 or len(theirs) < 2 or mine[-1] != theirs[-1]:
        return False  # different surname, or only one name to go on

    short, long = sorted(
        (mine[:-1], theirs[:-1]), key=lambda words: len("".join(words))
    )
    if not short or len("".join(short)) >= len("".join(long)):
        return False  # nothing is abbreviated, so there is nothing to decode

    if all(len(word) == 1 for word in short):
        return _initials(short) == _initials(long)
    return len(short) == 1 and short[0] == _initials(long)



def near_matches(
    name: str, index: dict, limit: int = 3, team: str | None = None
) -> list[tuple[float, str, str]]:
    """Plausible previous-season names for an unmatched player, best first.

    *team* is the player's team this season. Where it is given, a candidate
    from the same club clears a lower bar, and a candidate whose surname and
    initials line up is offered whatever it scores.

    Each result is (similarity, previous name, why) — "initials", "same club"
    or "spelling". Which rule fired is the fastest way to triage: an initials
    match is almost always real, a same-club one needs a look.
    """
    key = normalise(name)
    this_club = club(team) if team else None
    scored = []

    for candidate, entry in index.items():
        same_club = bool(
            this_club and entry.team and club(entry.team) == this_club
        )
        by_initials = same_person_by_initials(name, candidate)

        # Cheap gate before the expensive comparison — skipped for the two
        # cases that do not rely on the strings resembling each other.
        if not (same_club or by_initials):
            if not (set(key.split()) & set(candidate.split())) and abs(
                len(candidate) - len(key)
            ) > 4:
                continue

        ratio = SequenceMatcher(None, key, candidate).ratio()
        floor = SAME_CLUB_FLOOR if same_club else NEAR_MATCH_FLOOR
        if by_initials:
            scored.append((ratio, entry.name, "initials"))
        elif ratio >= NEAR_MATCH_FLOOR:
            scored.append((ratio, entry.name, "spelling"))
        elif ratio >= floor:
            scored.append((ratio, entry.name, "same club"))

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

    rejected = load_non_matches()
    near, brand_new = [], []
    for team, name, _ in unmatched:
        candidates = [
            (ratio, candidate, why)
            for ratio, candidate, why in near_matches(name, index, team=team)
            if normalise(candidate)
            not in rejected.get(normalise(name), ())
        ]
        (near if candidates else brand_new).append((team, name, candidates))

    if near:
        print(f"\n  NEEDS CONFIRMING — {len(near)} close but not exact:")
        rank = {"initials": 0, "spelling": 1, "same club": 2}
        near.sort(key=lambda row: (
            min(rank[why] for _, _, why in row[2]),
            -max(ratio for ratio, _, _ in row[2]),
        ))
        for team, name, candidates in near:
            options = ", ".join(
                f"{n!r} ({r:.0%}, {why})" for r, n, why in candidates
            )
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
