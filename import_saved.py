"""Publish results from league pages saved in your own browser.

Cloudflare challenges every scripted request to tabletennis365 — from GitHub
and from home alike — so the weekly update is done by hand: you open the pages
in an ordinary browser, save them, and this reads the saved files. Nothing
here contacts the league site.

    uv run python import_saved.py ~/Downloads/tt365            # import, publish
    uv run python import_saved.py ~/Downloads/tt365 --dry-run  # report only
    uv run python import_saved.py --links                      # pages to save

WEEKLY.md has the routine with real paths.

Two passes a week:

1. Save each division's fixtures page (``--links`` lists them) into one
   folder, and run this on it. It says which results are new, and prints the
   match card link for each one it has no card for.
2. Save those match cards into the same folder and run it again. Every new
   result with its card is merged and published; any still missing are listed.

Save with Ctrl+S as **"Webpage, HTML Only"**. Not "Complete": that keeps
downloading resources in the background and closing the tab cancels it, which
leaves a _files folder and no page. HTML Only writes one file immediately from
what is already on screen, which is all this reads. File names do not matter —
each page is recognised by its contents, and a card is matched to its fixture
by the two team names.
"""

import argparse
import json
import sys
from pathlib import Path

from cache import load_matches, merge_matches, save_matches
from models import Match, TeamResult
from parser_v2 import build_match, parse_fixtures, parse_match_card
from player_identity import normalise
from publish import commit_and_push, describe, stamp
from scraper import (
    CURRENT_SEASON, DIVISION_NAMES, PREMIER_SLUGS, _fixtures_url,
    _match_card_url, all_fixtures_url,
)
from tt365_ranking import parse_folder as parse_ranking
from webapp.export import export

TEAMS_DIR = Path(__file__).parent / "data"
RANKING_FILE = TEAMS_DIR / "tt365_ranking_{season}.json"


def stub_match(fixture: dict, division: int, season: str) -> Match:
    """A result with its score but no line-up.

    The fixtures page gives one row per match: who played whom and the team
    score, but not which player beat which. That is enough for the results
    list, the division table and the standings; only per-player records need
    the card.
    """
    return Match(
        division=division,
        date=fixture["date"],
        season=season,
        match_id=fixture["match_id"],
        home=TeamResult(fixture["home"], [], fixture["home_score"]),
        away=TeamResult(fixture["away"], [], fixture["away_score"]),
    )


def cached_ids(matches) -> set[str]:
    """Every player we have ever seen in a result, for recognising the table."""
    return {normalise(p.name)
            for m in matches
            for side in (m.home, m.away)
            for p in side.players}


def team_divisions(season: str) -> dict[str, int]:
    """Normalised team name → division, from the structure fetched earlier."""
    path = TEAMS_DIR / f"teams_{season}.json"
    teams = json.loads(path.read_text())["teams"]
    return {normalise(name): div for name, div in teams.items()}


def pair(home: str, away: str) -> tuple[str, str]:
    return normalise(home), normalise(away)


# The page of links this writes, which lands in the folder it also reads.
LINK_PAGE = "_cards_to_save.html"

# What a browser writes when you pick the wrong "Save as" option. MHTML is a
# MIME container, not HTML, so nothing here can read it.
SAVED_WRONG = {
    ".mhtml": 'saved as "Webpage, Single File" — re-save as '
              '"Webpage, HTML Only"',
    ".mht": 'saved as "Webpage, Single File" — re-save as '
            '"Webpage, HTML Only"',
    ".pdf": "printed to PDF rather than saved — use Ctrl+S, not Ctrl+P",
    ".txt": "saved as plain text, which loses the links the importer needs",
}


def read_folder(folder: Path, season: str) -> tuple[list[dict], list[dict], list[str]]:
    """(fixtures, cards, complaints) from every saved page.

    A folder of files it cannot read must not look like an empty one: the
    complaints name every file that was passed over and why, so "found
    nothing" always comes with a reason.
    """
    fixtures, cards, unknown = [], [], []
    pages = {p.stem for p in folder.iterdir()
             if p.suffix.lower() in (".html", ".htm")}
    for path in sorted(folder.iterdir()):
        if path.is_dir():
            # "Webpage, Complete" writes a _files folder and then the page.
            # A folder with no page beside it is a save that was cancelled
            # part-way — which is what closing the tab too early does.
            if path.name.endswith("_files") and path.name[:-6] not in pages:
                unknown.append(
                    f"{path.name[:-6]}: saved as \"Webpage, Complete\" but "
                    "the page never finished writing — re-save it as "
                    "\"Webpage, HTML Only\"")
            continue
        suffix = path.suffix.lower()
        if suffix in SAVED_WRONG:
            unknown.append(f"{path.name}: {SAVED_WRONG[suffix]}")
            continue
        if path.name == LINK_PAGE:
            continue  # our own list of links, not a saved page
        if "ranking" in path.name.lower():
            continue  # read separately, for the ratings rather than results
        if suffix not in (".html", ".htm"):
            unknown.append(f"{path.name}: not an HTML file")
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
    """The one page worth saving, with the per-division pages as a fallback.

    The combined page carries every division, and a fixture's division is
    looked up from the team rather than the page it came from, so one save
    covers the league — and --divisions still narrows which results are
    imported from it. The per-division pages are listed underneath in case
    the combined one turns out to need a click per division to fill in.
    """
    print("Save this one page — it carries every division:")
    show([all_fixtures_url(season)], open_them)
    print("\nIf that page comes up empty or only shows one division, save "
          "these instead\n(the Premier slug is a guess; use the site's own "
          "menu if it 404s):")
    for url in fixtures_links(season, only):
        print(f"  {url}")


def show(urls: list[str], open_them: bool = False) -> None:
    """Print each link. Opening a browser from here is not attempted.

    Three goes at launching one from the shell produced, in order: gio
    errors under WSL, a single tab where dozens were asked for, and Windows
    error dialogs. A printed path cannot misfire, and the links page is one
    click away once it is open.
    """
    for url in urls:
        print(f"  {url}")


def windows_path(path: Path) -> str | None:
    """`/mnt/c/Users/x/y` -> `C:\\Users\\x\\y`, for printing under WSL."""
    parts = path.resolve().parts
    if len(parts) > 2 and parts[0] == "/" and parts[1] == "mnt" and len(parts[2]) == 1:
        rest = "\\".join(parts[3:])
        return f"{parts[2].upper()}:\\{rest}"
    return None


def write_link_page(folder: Path, missing: list[tuple[int, dict]]) -> Path:
    """A page of the cards still to save, so they open from one click each.

    Opening dozens of tabs from the shell is unreliable — under WSL it does
    not work at all — and dozens of tabs is an awkward thing to work through
    anyway. One page, one link per card, is the same work without depending
    on anything being installed.
    """
    rows = "\n".join(
        f'<li><a href="{_match_card_url(f["match_id"])}" target="_blank">'
        f'{f["date"]} &middot; {"Prem" if d == 0 else f"D{d}"} &middot; '
        f'{f["home"]} v {f["away"]}</a></li>'
        for d, f in missing
    )
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Match cards to save</title>
<style>
 body {{ font: 16px/1.6 system-ui, sans-serif; max-width: 44rem; margin: 2rem auto;
        padding: 0 1rem; }}
 li {{ margin: .35rem 0; }}
 p {{ color: #555; }}
</style></head><body>
<h1>{len(missing)} match cards to save</h1>
<p>Open each, let it finish loading, then <b>Ctrl+S</b> into this same folder
as <b>Webpage, HTML Only</b>. Then run the importer again.</p>
<ol>{rows}</ol>
</body></html>"""
    path = folder / LINK_PAGE
    path.write_text(page)
    return path


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", nargs="?", type=Path,
                    help="folder holding the saved pages")
    ap.add_argument("--season", default=CURRENT_SEASON)
    ap.add_argument("--with-cards", action="store_true",
                    help="also expect a match card per result, for per-player "
                         "records. Without it a fixtures page alone is enough: "
                         "the team scores are stored and player ratings come "
                         "from the league's ranking")
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
                    help="accepted and ignored; opening a browser from the "
                         "shell proved unreliable, so the links page is "
                         "written and you open it yourself")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would be imported, change nothing")
    args = ap.parse_args()

    only = parse_divisions(args.divisions)
    if args.links or args.folder is None:
        print_links(args.season, args.open, only)
        return 0
    if str(args.folder) in ("", "."):
        print("No folder given — an unset shell variable reads as the current "
              "directory.\nPass the path to your saved pages in full.")
        return 1
    if not args.folder.is_dir():
        print(f"{args.folder} is not a folder.")
        return 1

    season = args.season
    cached = load_matches() or []
    known = {m.match_id for m in cached if m.season == season and m.match_id}
    divisions = team_divisions(season)

    ranking = parse_ranking(args.folder, set(divisions) | set(cached_ids(cached)))
    if ranking:
        path = Path(str(RANKING_FILE).format(season=season))
        path.write_text(json.dumps(ranking, indent=1, sort_keys=True))
        rated = sum(1 for v in ranking.values() if v.get("provisional"))
        print(f"Read the league's ranking: {len(ranking)} players, "
              f"{rated} with a rating -> {path.name}")

    fixtures, cards, unknown = read_folder(args.folder, season)
    for name in unknown:
        print(f"  ignored {name}")
    print(f"Read {len(fixtures)} played fixture(s) and {len(cards)} match card(s).")
    if not fixtures:
        if not any(args.folder.iterdir()):
            print(f"{args.folder} is empty — save the fixtures page into it "
                  "first.\n")
        else:
            print("Nothing in that folder could be read as a fixtures page.\n")
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
            if args.with_cards:
                missing.append((division, fixture))
                continue
            # No card wanted: keep the team score, which is what the results
            # list and the division table need. A card saved later fills in
            # the line-up without creating a duplicate.
            built.append(stub_match(fixture, division, season))
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

    if missing and args.with_cards:
        # Each link under its own fixture. Printed as two lists they were in
        # different orders — the fixtures sorted by date, the links not — so
        # line 12 of one was not line 12 of the other.
        print(f"\n{len(missing)} new result(s) still need their match card saved:")
        missing.sort(key=lambda m: (m[1]["date"] is None, m[1]["date"]))
        for division, f in missing:
            label = "Prem" if division == 0 else f"D{division}"
            print(f"\n  {f['date']}  {label:4s} {f['home']} v {f['away']}")
            print(f"    {_match_card_url(f['match_id'])}")

        page = write_link_page(args.folder, missing)
        windows = windows_path(page)
        print(f"\n  All {len(missing)} as clickable links: {windows or page}")

        print("  Open that file, then for each link: click it, let it load, "
              "Ctrl+S,\n  save as \"Webpage, HTML Only\", Ctrl+W.")

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
