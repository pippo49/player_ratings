"""Scrape fixture results for all divisions from tabletennis365.com."""

import re
import time
from datetime import date

import requests
from bs4 import BeautifulSoup, Tag

from models import Match, PlayerResult, TeamResult

BASE_URL = "https://www.tabletennis365.com"
SEASON = "Winter_2025-26"
LEAGUE = "CentralLondon"

DIVISION_NAMES = [
    "Division_One",
    "Division_Two",
    "Division_Three",
    "Division_Four",
    "Division_Five",
    "Division_Six",
    "Division_Seven",
]

DIVISION_NUMBER = {name: i + 1 for i, name in enumerate(DIVISION_NAMES)}

REQUEST_DELAY = 1.0  # polite delay between requests (seconds)


def _fixtures_url(division: str) -> str:
    return f"{BASE_URL}/{LEAGUE}/Fixtures/{SEASON}/{division}"


def _fetch_html(url: str) -> str:
    headers = {"User-Agent": "Mozilla/5.0 (compatible; ratings-bot/1.0)"}
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.text


def _extract_player_id(href: str) -> str:
    """Extract numeric player ID from a player stats URL.

    URL format: /CentralLondon/Results/Player/Statistics/Season/Name/12345
    """
    parts = href.rstrip("/").split("/")
    for part in reversed(parts):
        if part.isdigit():
            return part
    return parts[-1]


def _parse_team_side(side_div: Tag) -> TeamResult | None:
    """Parse a <div class="home"> or <div class="away"> block."""
    # Aggregate score
    score_div = side_div.find("div", class_="score")
    total_score = 0
    if score_div:
        m = re.search(r"\d+", score_div.get_text())
        total_score = int(m.group()) if m else 0

    # Team name
    team_link = side_div.find("a", href=re.compile(r"/Results/Team/Statistics/"))
    if not team_link:
        return None
    team_name = team_link.get_text(strip=True)

    # Players — each in a <div class="playerName">
    players: list[PlayerResult] = []
    for p_div in side_div.find_all("div", class_="playerName"):
        link = p_div.find("a", href=re.compile(r"/Results/Player/Statistics/"))
        if not link:
            continue
        name = link.get_text(strip=True)
        player_id = _extract_player_id(link["href"])
        score_m = re.search(r"\((\d)\)", p_div.get_text())
        games_won = int(score_m.group(1)) if score_m else 0
        players.append(PlayerResult(name=name, player_id=player_id, games_won=games_won))

    if len(players) < 2:
        return None  # unplayed fixture

    return TeamResult(name=team_name, players=players[:3], total_score=total_score)


def _parse_matches(html: str, division: int) -> list[Match]:
    """Parse all played matches from a division fixtures page."""
    soup = BeautifulSoup(html, "html.parser")
    matches: list[Match] = []

    for home_div in soup.find_all("div", class_="home"):
        container = home_div.parent
        away_div = container.find("div", class_="away")
        if away_div is None:
            continue

        # Date from <time datetime="YYYY-MM-DD">
        match_date: date | None = None
        time_el = container.find("time")
        if time_el and time_el.get("datetime"):
            try:
                match_date = date.fromisoformat(time_el["datetime"])
            except ValueError:
                pass

        # Match ID from MatchCard link
        match_id = ""
        mc_link = container.find("a", href=re.compile(r"/MatchCard/"))
        if mc_link:
            match_id = mc_link["href"].rstrip("/").split("/")[-1]

        home = _parse_team_side(home_div)
        away = _parse_team_side(away_div)

        if home is None or away is None:
            continue

        match = Match(division=division, date=match_date, home=home, away=away, match_id=match_id)
        if match.played:
            matches.append(match)

    return matches


def scrape_all_divisions(verbose: bool = True) -> list[Match]:
    """Fetch and parse fixtures for all 7 divisions. Returns played matches only."""
    all_matches: list[Match] = []

    for div_name in DIVISION_NAMES:
        div_num = DIVISION_NUMBER[div_name]
        url = _fixtures_url(div_name)
        if verbose:
            print(f"Fetching Division {div_num} ({div_name})… ", end="", flush=True)

        try:
            html = _fetch_html(url)
            matches = _parse_matches(html, division=div_num)
            all_matches.extend(matches)
            if verbose:
                print(f"{len(matches)} matches parsed.")
        except requests.HTTPError as e:
            print(f"HTTP error: {e}")
        except Exception as e:
            print(f"Error: {e}")

        time.sleep(REQUEST_DELAY)

    return all_matches
