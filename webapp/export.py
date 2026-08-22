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


def export(verbose: bool = True) -> Path | None:
    """Recompute ratings from the cache and write them into the static bundle."""
    matches = load_matches()
    if not matches:
        if verbose:
            print("No cached matches — nothing to export.")
        return None

    payload = build_payload(matches)
    payload["live"] = False  # a committed snapshot cannot scrape
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
