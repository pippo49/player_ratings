"""Publish results from league pages saved in your own browser.

Cloudflare challenges every scripted request to tabletennis365 — from GitHub
and from home alike — so the weekly update is done by hand: you open the pages
in an ordinary browser, save them, and this reads the saved files. Nothing
here contacts the league site.

    uv run python import_saved.py ~/Downloads/tt365            # import, publish
    uv run python import_saved.py ~/Downloads/tt365 --dry-run  # report only
    uv run python import_saved.py --links                      # pages to open
    uv run python import_saved.py ~/Downloads/tt365 --open     # ...in your browser

Two passes a week:

1. Save each division's fixtures page (``--links`` lists them) into one
   folder, and run this on it. It says which results are new, and prints the
   match card link for each one it has no card for.
2. Save those match cards into the same folder and run it again. Every new
   result with its card is merged and published; any still missing are listed.

Save with Ctrl+S, either "Webpage, HTML only" or "Webpage, Complete". File
names do not matter: each page is recognised by its contents, and a card is
matched to its fixture by the two team names.
"""

import argparse
import json
import sys
import webbrowser
from pathlib import Path

from cache import load_matches, merge_matches, save_matches
from parser_v2 import build_match, parse_fixtures, parse_match_card
from player_identity import normalise
from publish import commit_and_push, describe, stamp
from scraper import (
    CURRENT_SEASON, DIVISION_NAMES, PREMIER_SLUGS, _fixtures_url,
    _match_card_url,
)
from webapp.export import export

TEAMS_DIR = Path(__file__).parent / "data"


def team_divisions(season: str) -> dict[str, int]:
    """Normalised team name → division, from the structure fetched earlier."""
    path = TEAMS_DIR / f"teams_{season}.json"
    teams = json.loads(path.read_text())["teams"]
    return {normalise(name): div for name, div in teams.items()}


def pair(home: str, away: str) -> tuple[str, str]:
    return normalise(home), normalise(away)


def read_folder(folder: Path, season: str) -> tuple[list[dict], list[dict], list[str]]:
    """(fixtures, cards, unrecognised file names) from every saved page."""
    fixtures, cards, unknown = [], [], []
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() not in (".html", ".htm"):
            continue
        html = path.read_text(errors="replace")
        card = parse_match_card(html)
        if card is not None:
            cards.append(card)
            continue
        found = parse_fixtures(html, season)
        if found:
            fixtures.extend(found)
        elif "Just a moment" in html:
            unknown.append(f"{path.name} (saved before the browser check finished)")
        else:
            unknown.append(path.name)
    return fixtures, cards, unknown


def fixtures_links(season: str) -> list[str]:
    return [_fixtures_url(name, season) for name in (PREMIER_SLUGS[0], *DIVISION_NAMES)]


def print_links(season: str, open_them: bool = False) -> None:
    print("Fixtures pages to save (the Premier slug may differ):")
    show(fixtures_links(season), open_them)


def show(urls: list[str], open_them: bool) -> None:
    """Print each link, and with --open hand it to your own browser to load."""
    for url in urls:
        print(f"  {url}")
        if open_them:
            webbrowser.open_new_tab(url)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", nargs="?", type=Path,
                    help="folder holding the saved pages")
    ap.add_argument("--season", default=CURRENT_SEASON)
    ap.add_argument("--links", action="store_true",
                    help="list the fixtures pages to save, and stop")
    ap.add_argument("--open", action="store_true",
                    help="open the pages still to save as tabs in your browser")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be imported, change nothing")
    args = ap.parse_args()

    if args.links or args.folder is None:
        print_links(args.season, args.open)
        return 0
    if not args.folder.is_dir():
        print(f"{args.folder} is not a folder.")
        return 1

    season = args.season
    cached = load_matches() or []
    known = {m.match_id for m in cached if m.season == season and m.match_id}
    divisions = team_divisions(season)

    fixtures, cards, unknown = read_folder(args.folder, season)
    for name in unknown:
        print(f"  ignored {name}: not a fixtures page or a match card")
    print(f"Read {len(fixtures)} played fixture(s) and {len(cards)} match card(s).")
    if not fixtures:
        print("No fixtures pages in that folder — save those first.\n")
        print_links(season, args.open)
        return 1

    new = {}
    for f in fixtures:
        if f["match_id"] and f["match_id"] not in known:
            new[pair(f["home"], f["away"])] = f
    cards_by_pair = {pair(c["home"], c["away"]): c for c in cards}

    built, missing, problems = [], [], []
    for key, fixture in new.items():
        card = cards_by_pair.get(key)
        if card is None:
            missing.append(fixture)
            continue
        division = divisions.get(key[0], divisions.get(key[1]))
        if division is None:
            problems.append(f"{fixture['home']} v {fixture['away']}: team not in "
                            f"teams_{season}.json, so its division is unknown")
            continue
        match = build_match(fixture, card, division=division, season=season)
        if match is None or not match.played:
            problems.append(f"{fixture['home']} v {fixture['away']}: card has no singles")
            continue
        built.append(match)

    for line in problems:
        print(f"  skipped {line}")

    if missing:
        print(f"\n{len(missing)} new result(s) still need their match card saved:")
        for f in sorted(missing, key=lambda f: (f["date"] is None, f["date"])):
            print(f"  {f['date']}  {f['home']} v {f['away']}")
        show([_match_card_url(f["match_id"]) for f in missing], args.open)

    if not new:
        stamp("Nothing new on those pages — the app is already up to date.")
        return 0

    matches, added = merge_matches(cached, built)
    if not added:
        print("\nNothing to publish yet.")
        return 1 if missing else 0

    stamp(f"{added} new result(s) ready:")
    stamp("\n".join(describe(built)))

    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return 0

    save_matches(matches)
    export()
    status = commit_and_push(f"Add {added} new result(s) from saved pages", added)
    if missing:
        print(f"\nSave the {len(missing)} card(s) above and run again for the rest.")
    return status


if __name__ == "__main__":
    sys.exit(main())
