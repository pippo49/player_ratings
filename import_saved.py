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
            unknown.append(
                f"{path.name}: saved while the browser check was still "
                "running — open it again, wait for the results, then re-save")
        else:
            unknown.append(f"{path.name}: not a fixtures page or a match card")
    return fixtures, cards, unknown


# Premier is division 0, as everywhere else in the project.
SLUG_FOR = {0: PREMIER_SLUGS[0], **{i: n for i, n in enumerate(DIVISION_NAMES, 1)}}


def parse_divisions(text: str | None) -> set[int] | None:
    """"3,4,7" -> {3, 4, 7}. None means every division."""
    if not text:
        return None
    wanted = set()
    for part in text.split(","):
        part = part.strip().lower()
        if part in ("prem", "premier"):
            wanted.add(0)
        elif part.isdigit() and int(part) in SLUG_FOR:
            wanted.add(int(part))
        else:
            raise SystemExit(f"{part!r} is not a division — use 0 (or prem) to 7")
    return wanted


def fixtures_links(season: str, only: set[int] | None = None) -> list[str]:
    return [_fixtures_url(SLUG_FOR[d], season)
            for d in sorted(SLUG_FOR) if only is None or d in only]


def print_links(season: str, open_them: bool = False,
                only: set[int] | None = None) -> None:
    print("Fixtures pages to save (the Premier slug may differ):")
    show(fixtures_links(season, only), open_them)


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
    ap.add_argument("--divisions", metavar="3,4,7",
                    help="only these divisions (0 or prem for Premier). The "
                         "weekly saving is roughly five pages per division, "
                         "so narrowing it to the ones you follow is the "
                         "difference between an afternoon and ten minutes. "
                         "Ratings in the divisions you skip simply stop "
                         "moving until you import them.")
    ap.add_argument("--links", action="store_true",
                    help="list the fixtures pages to save, and stop")
    ap.add_argument("--open", action="store_true",
                    help="open the pages still to save as tabs in your browser")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be imported, change nothing")
    args = ap.parse_args()

    only = parse_divisions(args.divisions)
    if args.links or args.folder is None:
        print_links(args.season, args.open, only)
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
        print(f"  ignored {name}")
    print(f"Read {len(fixtures)} played fixture(s) and {len(cards)} match card(s).")
    if not fixtures:
        print("No fixtures pages in that folder — save those first.\n")
        print_links(season, args.open, only)
        return 1

    new = {}
    for f in fixtures:
        if f["match_id"] and f["match_id"] not in known:
            new[pair(f["home"], f["away"])] = f
    cards_by_pair = {pair(c["home"], c["away"]): c for c in cards}

    built, missing, problems, skipped = [], [], [], 0
    for key, fixture in new.items():
        division = divisions.get(key[0], divisions.get(key[1]))
        if division is None:
            problems.append(f"{fixture['home']} v {fixture['away']}: team not in "
                            f"teams_{season}.json, so its division is unknown")
            continue
        if only is not None and division not in only:
            skipped += 1
            continue
        card = cards_by_pair.get(key)
        if card is None:
            missing.append(fixture)
            continue
        match = build_match(fixture, card, division=division, season=season)
        if match is None or not match.played:
            problems.append(f"{fixture['home']} v {fixture['away']}: card has no singles")
            continue
        built.append(match)

    for line in problems:
        print(f"  skipped {line}")
    if skipped:
        print(f"  skipped {skipped} result(s) outside --divisions {args.divisions}")

    if missing:
        print(f"\n{len(missing)} new result(s) still need their match card saved:")
        for f in sorted(missing, key=lambda f: (f["date"] is None, f["date"])):
            print(f"  {f['date']}  {f['home']} v {f['away']}")
        show([_match_card_url(f["match_id"]) for f in missing], args.open)

    if not (built or missing):
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
