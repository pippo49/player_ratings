"""Report what a season's pages on tabletennis365 actually contain.

Before fixtures are published there are no results to parse, but the
divisions and teams are already listed somewhere. This fetches the likely
pages for a season and reports what it finds, so the scraper can be pointed
at the right one.

    .venv/bin/python3 probe_season.py 2026-27

Paste the output back if the team lists come out empty — the page layout
will need a different selector.
"""

import re
import sys
import time

import requests
from bs4 import BeautifulSoup

from scraper import (
    BASE_URL,
    DIVISION_NAMES,
    LEAGUE,
    REQUEST_DELAY,
    _fetch_html,
    _parse_matches,
    _season_slug,
)

# Sections that might carry the division/team structure before fixtures exist.
SECTIONS = ["Fixtures", "Tables", "Results"]


def probe(season: str, division_name: str) -> None:
    slug = _season_slug(season)
    print(f"\n{'=' * 72}\n  {season} — {division_name}\n{'=' * 72}")

    for section in SECTIONS:
        url = f"{BASE_URL}/{LEAGUE}/{section}/{slug}/{division_name}"
        try:
            response = requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; ratings-bot/1.0)"},
                timeout=30,
            )
        except Exception as exc:
            print(f"  {section:9} — request failed: {type(exc).__name__}: {exc}")
            continue

        print(f"  {section:9} — HTTP {response.status_code}  ({len(response.text)} bytes)")
        if response.status_code != 200:
            time.sleep(REQUEST_DELAY)
            continue

        soup = BeautifulSoup(response.text, "html.parser")
        title = soup.find("title")
        if title:
            print(f"    title      : {title.get_text(strip=True)}")

        teams = sorted({
            a.get_text(strip=True)
            for a in soup.find_all("a", href=re.compile(r"/Results/Team/Statistics/"))
            if a.get_text(strip=True)
        })
        print(f"    team links : {len(teams)}")
        for name in teams[:12]:
            print(f"       - {name}")
        if len(teams) > 12:
            print(f"       … and {len(teams) - 12} more")

        players = soup.find_all("a", href=re.compile(r"/Results/Player/Statistics/"))
        print(f"    player links: {len(players)}")

        if section == "Fixtures":
            parsed = _parse_matches(response.text, division=1, season=season)
            print(f"    played matches parsed: {len(parsed)}")

        time.sleep(REQUEST_DELAY)


def main() -> None:
    season = sys.argv[1] if len(sys.argv) > 1 else "2026-27"
    only = sys.argv[2] if len(sys.argv) > 2 else None

    print(f"Probing {season} — {_season_slug(season)}")
    names = [only] if only else DIVISION_NAMES[:2]
    for division_name in names:
        probe(season, division_name)

    print(
        "\nLooking for: which section lists the teams, and whether any "
        "fixtures\nor results exist yet. Run with a division name as a second "
        "argument\n(e.g. Division_Three) to probe just one."
    )


if __name__ == "__main__":
    main()
