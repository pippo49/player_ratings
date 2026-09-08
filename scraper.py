"""Scrape fixture results for all divisions from tabletennis365.com."""

import re
import time
from collections.abc import Callable
from datetime import date

import requests
from bs4 import BeautifulSoup, Tag

from models import Match, PlayerResult, TeamResult

BASE_URL = "https://www.tabletennis365.com"
LEAGUE = "CentralLondon"

# Seasons the app knows about, oldest first. The last is the current one:
# ratings carry forward from each season into the next. Add the new season
# here when its pages go up on tabletennis365.
SEASONS = ["2025-26", "2026-27"]
CURRENT_SEASON = SEASONS[-1]

# From 2026/27 the league runs eight tiers: a Premier division above
# Divisions One to Seven (94 entries, max 12 per division). The URL slug for
# the top tier is not certain, so candidates are tried in order and the first
# that returns teams wins.
PREMIER_SLUGS = ["Premier", "Premier_Division", "Premier_Div", "PremierDivision"]

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

# Premier sits above Division One, so it numbers below it. Zero keeps the
# existing 1-7 numbering meaningful for 2025/26 data, where those numbers
# referred to a seven-tier league.
PREMIER_DIVISION = 0
for _slug in PREMIER_SLUGS:
    DIVISION_NUMBER[_slug] = PREMIER_DIVISION

REQUEST_DELAY = 1.0  # polite delay between requests (seconds)


def _season_slug(season: str) -> str:
    """"2026-27" -> "Winter_2026-27", the form used in fixture URLs."""
    return f"Winter_{season}"


def _fixtures_url(division: str, season: str) -> str:
    return f"{BASE_URL}/{LEAGUE}/Fixtures/{_season_slug(season)}/{division}"


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


def _parse_matches(html: str, division: int, season: str) -> list[Match]:
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

        match = Match(
            division=division, date=match_date, home=home, away=away,
            match_id=match_id, season=season,
        )
        if match.played:
            matches.append(match)

    return matches


def scrape_division_page(division_name: str, division: int, season: str) -> list[Match]:
    """Fetch and parse one division's fixtures page for one season."""
    html = _fetch_html(_fixtures_url(division_name, season))
    matches = _parse_matches(html, division=division, season=season)
    return matches


def scrape_season(
    season: str,
    verbose: bool = True,
    progress: Callable[[str, int, int, int | None, str | None], None] | None = None,
) -> list[Match]:
    """Fetch and parse fixtures for all 7 divisions of one season."""
    all_matches: list[Match] = []
    total = len(DIVISION_NAMES)

    for div_name in DIVISION_NAMES:
        div_num = DIVISION_NUMBER[div_name]
        url = _fixtures_url(div_name, season)
        if verbose:
            print(f"Fetching {season} Division {div_num} ({div_name})… ", end="", flush=True)

        try:
            matches = scrape_division_page(div_name, div_num, season)
            all_matches.extend(matches)
            if verbose:
                print(f"{len(matches)} matches parsed.")
            if progress:
                progress(season, div_num, total, len(matches), None)
        except requests.HTTPError as e:
            # A season whose pages are not up yet 404s; that is not an error
            # worth shouting about, just nothing to fetch.
            note = "not published yet" if e.response is not None and e.response.status_code == 404 else str(e)
            print(f"Division {div_num} ({season}): {note}")
            if progress:
                progress(season, div_num, total, None, note)
        except Exception as e:
            print(f"Error fetching {season} Division {div_num} ({url}): {type(e).__name__}: {e}")
            if progress:
                progress(season, div_num, total, None, f"{type(e).__name__}: {e}")

        time.sleep(REQUEST_DELAY)

    return all_matches


def scrape_all_divisions(
    verbose: bool = True,
    progress: Callable[[str, int, int, int | None, str | None], None] | None = None,
    seasons: list[str] | None = None,
) -> list[Match]:
    """Fetch and parse fixtures for every division of every known season.

    Defaults to every season in SEASONS, so a run picks up both last
    season's completed results and whatever the new one has so far.

    *progress*, if given, is called once per division as
    ``progress(season, division, total_divisions, matches_parsed, error)`` —
    with ``matches_parsed`` None and ``error`` set when that division failed.
    It lets callers (such as the web app) report progress somewhere other
    than stdout while the scrape is still running.
    """
    all_matches: list[Match] = []
    for season in (seasons or SEASONS):
        all_matches.extend(scrape_season(season, verbose=verbose, progress=progress))
    return all_matches
