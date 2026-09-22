"""Scrape each team's squad from the league's team pages.

The 2026/27 site is a redesign: squads live on
`/Results/Team?leagueName=...&divisionName=...&teamName=...` and each player
is an `a.tt-player-link` carrying their name and id.

Squads fill up over the first weeks of a season as clubs register players, so
this is meant to run repeatedly — it rewrites the file each time rather than
merging, so a player who leaves disappears.

    .venv/bin/python3 fetch_squads.py 2026-27
"""

import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from scraper import (
    BASE_URL,
    DIVISION_NAMES,
    LEAGUE,
    PREMIER_DIVISION,
    REQUEST_DELAY,
    _season_slug,
)

DATA_DIR = Path(__file__).resolve().parent / "data"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ratings-bot/1.0)"}

PLAYER_LINK = re.compile(r"/Results/Player\b")
PLAYER_ID = re.compile(r"[?&]id=(\d+)")


def division_label(number: int) -> str:
    """0 -> 'Premier', 4 -> 'Division Four', matching the site's own wording."""
    if number == PREMIER_DIVISION:
        return "Premier"
    return DIVISION_NAMES[number - 1].replace("_", " ")


def team_url(season: str, division: int, team: str) -> str:
    league = _season_slug(season).replace("_", " ")
    return (
        f"{BASE_URL}/{LEAGUE}/Results/Team"
        f"?leagueName={quote(league)}"
        f"&divisionName={quote(division_label(division))}"
        f"&teamName={quote(team)}"
    )


def squad_on_page(html: str) -> list[dict]:
    """Players listed on a team page, as {id, name}."""
    soup = BeautifulSoup(html, "html.parser")
    seen: dict[str, str] = {}
    for link in soup.find_all("a", class_="tt-player-link"):
        href = link.get("href") or ""
        match = PLAYER_ID.search(href)
        name = link.get_text(strip=True)
        if not match or not name:
            continue
        seen.setdefault(match.group(1), name)

    # Fall back to any player link if the class ever changes under us.
    if not seen:
        for link in soup.find_all("a", href=PLAYER_LINK):
            match = PLAYER_ID.search(link.get("href") or "")
            name = link.get_text(strip=True)
            if match and name:
                seen.setdefault(match.group(1), name)

    return [{"id": pid, "name": name} for pid, name in seen.items()]


def fetch(season: str) -> dict:
    structure_path = DATA_DIR / f"teams_{season}.json"
    if not structure_path.exists():
        raise SystemExit(
            f"No {structure_path.name} — run fetch_structure.py {season} first."
        )
    teams = json.loads(structure_path.read_text())["teams"]

    squads: dict[str, dict] = {}
    empty = []
    for team, division in sorted(teams.items(), key=lambda kv: (kv[1], kv[0])):
        url = team_url(season, division, team)
        try:
            response = requests.get(url, headers=HEADERS, timeout=30)
        except Exception as exc:
            print(f"  {team:32} request failed — {type(exc).__name__}")
            continue
        finally:
            time.sleep(REQUEST_DELAY)

        if response.status_code != 200:
            print(f"  {team:32} HTTP {response.status_code}")
            continue

        players = squad_on_page(response.text)
        squads[team] = {"division": division, "players": players}
        if players:
            print(f"  {team:32} D{division}  {len(players):>2} players")
        else:
            empty.append(team)

    if empty:
        print(f"\n  {len(empty)} team(s) with no players registered yet:")
        for team in empty[:15]:
            print(f"    {team}")
    return squads


def main() -> None:
    season = sys.argv[1] if len(sys.argv) > 1 else "2026-27"
    print(f"Fetching {season} squads\n")
    squads = fetch(season)

    total = sum(len(s["players"]) for s in squads.values())
    if not total:
        print("\nNo players found at all — the page layout has probably changed.")
        raise SystemExit(1)

    DATA_DIR.mkdir(exist_ok=True)
    path = DATA_DIR / f"squads_{season}.json"
    path.write_text(json.dumps({"season": season, "teams": squads}, indent=1) + "\n")

    sized = defaultdict(int)
    for s in squads.values():
        sized[len(s["players"])] += 1
    print(f"\nWrote {path.name}: {len(squads)} teams, {total} players")
    print("  squad sizes:", ", ".join(
        f"{n} players x{c}" for n, c in sorted(sized.items())
    ))


if __name__ == "__main__":
    main()
