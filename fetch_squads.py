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

from cache import load_matches
from player_identity import normalise
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


def appearances_by_team(season: str) -> dict[str, list[dict]]:
    """{team: players who have turned out for it} from the cached results.

    The league's team page serves two different lists. Before a team plays it
    is the squad registered for the season — complete and authoritative. Once
    it has played, the page becomes a results view, which both drops squad
    members who have not yet turned out *and* picks up the opposition's
    players. Neither direction is recoverable from the page, so for a team
    that has played the squad comes from what was already recorded plus the
    match cards, which attribute each player to the right side.
    """
    try:
        matches = load_matches() or []
    except Exception:
        return {}

    by_team: dict[str, dict[str, dict]] = {}
    for match in matches:
        if match.season != season:
            continue
        for side in (match.home, match.away):
            players = by_team.setdefault(side.name, {})
            for player in side.players:
                players.setdefault(normalise(player.name), {
                    "id": player.player_id,
                    "name": player.name,
                })
    return {team: list(players.values()) for team, players in by_team.items()}


def merge_squads(
    scraped: dict[str, dict],
    existing: dict[str, dict],
    appeared: dict[str, list[dict]],
) -> dict[str, dict]:
    """Fold a fresh scrape into what is already recorded.

    A team that has not played takes the page as gospel: it is still the
    registration list, so a player who de-registers really does disappear.
    A team that has played ignores the page — see appearances_by_team — and
    keeps its recorded squad plus anyone the results show turning out for it,
    which is how a mid-season signing still gets picked up.
    """
    merged: dict[str, dict] = {}

    for team, info in scraped.items():
        held = existing.get(team, {}).get("players", [])
        turned_out = appeared.get(team, [])

        if not turned_out:
            merged[team] = info
            continue

        base = held or info["players"]
        seen = {normalise(p["name"]) for p in base}
        added = [p for p in turned_out if normalise(p["name"]) not in seen]
        merged[team] = {**info, "players": base + added}

    # A team the scrape could not reach at all keeps whatever was recorded.
    for team, info in existing.items():
        if team not in merged and info.get("players"):
            merged[team] = info
    return merged


def main() -> None:
    season = sys.argv[1] if len(sys.argv) > 1 else "2026-27"
    print(f"Fetching {season} squads\n")
    scraped = fetch(season)

    total = sum(len(s["players"]) for s in scraped.values())
    if not total:
        print("\nNo players found at all — the page layout has probably changed.")
        raise SystemExit(1)

    DATA_DIR.mkdir(exist_ok=True)
    path = DATA_DIR / f"squads_{season}.json"
    existing = (
        json.loads(path.read_text()).get("teams", {}) if path.exists() else {}
    )
    appeared = appearances_by_team(season)
    squads = merge_squads(scraped, existing, appeared)
    if appeared:
        print(f"\n  {len(appeared)} teams have played — their page is a results "
              f"view that drops squad members and lists opponents, so their "
              f"squads come from what was recorded plus the match cards")
    total = sum(len(s["players"]) for s in squads.values())
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
