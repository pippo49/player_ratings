"""Scrape which teams are in which division for a season, before fixtures exist.

Divisions and teams are published well before any results, but there are no
matches to infer the structure from. This fetches it and writes
`data/teams_<season>.json`, which season_transition.py prefers over its
inferred promotion/relegation map.

    .venv/bin/python3 fetch_structure.py 2026-27

Run probe_season.py first if this finds nothing — the page layout may differ
from 2025/26, in which case TEAM_LINK below needs adjusting.
"""

import json
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from scraper import (
    BASE_URL,
    DIVISION_NAMES,
    DIVISION_NUMBER,
    LEAGUE,
    REQUEST_DELAY,
    _season_slug,
)

OUTPUT_DIR = Path(__file__).resolve().parent / "data"

# Team pages are linked the same way from tables, fixtures and results.
TEAM_LINK = re.compile(r"/Results/Team/Statistics/")

# Tables list every team in the division even with no results; fixtures only
# help once they are published. Tried in order, first one with teams wins.
SECTIONS = ["Tables", "Fixtures", "Results"]


def _team_id(href: str) -> str:
    """The numeric team ID from a team statistics URL, or the URL itself."""
    parts = href.rstrip("/").split("/")
    for part in reversed(parts):
        if part.isdigit():
            return part
    return href


def _teams_on_page(html: str) -> list[str]:
    """Team names on a page, one per team.

    The same team is linked more than once per page — the layout carries an
    abbreviated name for narrow screens alongside the full one ("Fulham
    Brunsw 2" and "Fulham Brunswick 2"), and both are links. Keying on the
    team ID in the URL rather than the link text collapses those, and the
    longest variant is kept because that is the form the match pages use.
    """
    soup = BeautifulSoup(html, "html.parser")
    by_id: dict[str, set[str]] = {}
    order: list[str] = []
    for link in soup.find_all("a", href=TEAM_LINK):
        name = link.get_text(strip=True)
        if not name:
            continue
        team_id = _team_id(link["href"])
        if team_id not in by_id:
            by_id[team_id] = set()
            order.append(team_id)
        by_id[team_id].add(name)

    names = []
    for team_id in order:
        variants = by_id[team_id]
        best = max(sorted(variants), key=len)
        if len(variants) > 1:
            others = ", ".join(sorted(v for v in variants if v != best))
            print(f"      {best!r} also listed as {others}")
        names.append(best)
    return names


def fetch_division(season: str, division_name: str) -> list[str]:
    """Return the teams in one division, trying each section in turn."""
    for section in SECTIONS:
        url = f"{BASE_URL}/{LEAGUE}/{section}/{_season_slug(season)}/{division_name}"
        try:
            response = requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; ratings-bot/1.0)"},
                timeout=30,
            )
        except Exception as exc:
            print(f"    {section}: request failed ({type(exc).__name__})")
            continue
        finally:
            time.sleep(REQUEST_DELAY)

        if response.status_code != 200:
            print(f"    {section}: HTTP {response.status_code}")
            continue

        teams = _teams_on_page(response.text)
        if teams:
            print(f"    {section}: {len(teams)} teams")
            return teams
        print(f"    {section}: no team links found")
    return []


def fetch(season: str) -> dict[str, int]:
    structure: dict[str, int] = {}
    for division_name in DIVISION_NAMES:
        number = DIVISION_NUMBER[division_name]
        print(f"  Division {number} ({division_name})")
        for team in fetch_division(season, division_name):
            if team in structure:
                print(f"    ! {team} already seen in division {structure[team]}")
                continue
            structure[team] = number
    return structure


def main() -> None:
    season = sys.argv[1] if len(sys.argv) > 1 else "2026-27"
    print(f"Fetching {season} structure…\n")
    structure = fetch(season)

    if not structure:
        print("\nNo teams found. Run probe_season.py to see what the pages contain.")
        return

    OUTPUT_DIR.mkdir(exist_ok=True)
    path = OUTPUT_DIR / f"teams_{season}.json"
    path.write_text(json.dumps(
        {"season": season, "teams": dict(sorted(structure.items()))}, indent=2
    ) + "\n")

    per_division: dict[int, int] = {}
    for division in structure.values():
        per_division[division] = per_division.get(division, 0) + 1

    print(f"\nWrote {path.relative_to(Path(__file__).resolve().parent)}"
          f" — {len(structure)} teams")
    for division in sorted(per_division):
        print(f"  Division {division}: {per_division[division]} teams")
    print("\nCommit it to publish the real structure.")


if __name__ == "__main__":
    main()
