"""Write the ratings payload into the static bundle so it can be committed.

The web app reads one file, `webapp/static/ratings.json`. When the local
server is running it serves that path from a live calculation; when the
bundle is hosted as plain static files (or opened offline on a phone) the
committed file is what gets read. Same path either way, so the front end
does not care which mode it is in.

    python -m webapp.export
"""

import json
from pathlib import Path

from cache import load_matches
from webapp.api import build_payload

OUTPUT = Path(__file__).parent / "static" / "ratings.json"


def check(payload: dict) -> list[str]:
    """Assertions over the payload that have each caught a real bug.

    Cheap to run and loud when they fail, which is the point: every one of
    these held right up until some change in how the league records things
    quietly broke it, and the symptom was wrong numbers rather than a crash.
    """
    problems = []

    # A player's seasons must account for their whole career. Catches a
    # record filed under an identity the ratings do not use.
    for p in payload["players"]:
        seasons = p.get("by_season", {})
        if sum(v["played"] for v in seasons.values()) != p["played"] or sum(
            v["won"] for v in seasons.values()
        ) != p["won"]:
            problems.append(
                f"{p['name']}: seasons {seasons} do not sum to career "
                f"{p['won']}/{p['played']}"
            )

    # One row per player, except where two really do share a name. Those are
    # kept apart on purpose and the payload names them, so only an unexpected
    # duplicate is a problem — the kind that means one person has been split
    # in two by an identity that does not match everywhere.
    # The form badge and the rows the app shows under it are the same three
    # matches, so they must agree. They are computed from one list, which is
    # exactly why this is worth asserting: the previous version kept the
    # number and the matches apart, and nobody could tell a sweep inside a
    # bad run from a bad night.
    for p in payload["players"]:
        rows = p.get("form_detail") or []
        if not rows:
            continue
        if len(rows) != p["form_matches"]:
            problems.append(
                f"{p['name']}: form over {p['form_matches']} matches but "
                f"{len(rows)} rows"
            )
        total = sum(row[4] for row in rows)
        if abs(total - p["form"]) > 0.15:  # each row is rounded to 0.1
            problems.append(
                f"{p['name']}: form rows sum to {total:+.1f}, badge says "
                f"{p['form']:+.1f}"
            )

    known = {n.casefold() for n in payload.get("ambiguous_names", [])}
    seen: dict[str, int] = {}
    for p in payload["players"]:
        seen[p["name"]] = seen.get(p["name"], 0) + 1
    for name, n in seen.items():
        if n > 1 and name.casefold() not in known:
            problems.append(f"{name}: {n} rows share this name")

    return problems


def export(verbose: bool = True) -> Path | None:
    """Recompute ratings from the cache and write them into the static bundle."""
    matches = load_matches()
    if not matches:
        if verbose:
            print("No cached matches — nothing to export.")
        return None

    payload = build_payload(matches)
    payload["live"] = False  # a committed snapshot cannot scrape

    problems = check(payload)
    if problems and verbose:
        print(f"CHECK: {len(problems)} problem(s) in the payload")
        for line in problems[:10]:
            print(f"  {line}")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, separators=(",", ":")))

    if verbose:
        size = OUTPUT.stat().st_size
        print(
            f"Wrote {OUTPUT.relative_to(Path(__file__).parent.parent)} "
            f"— {payload['player_count']} players, {payload['match_count']} matches, "
            f"{size / 1024:.0f} KB"
        )
        print("Commit it to publish the update.")
    return OUTPUT


if __name__ == "__main__":
    export()
