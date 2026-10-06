"""Scrape fixture results for all divisions from tabletennis365.com.

The 2026/27 site redesign moved results off the fixtures page and onto a card
per fixture, so parsing lives in parser_v2 and this module is the fetching and
per-division bookkeeping around it.
"""

import time
from collections.abc import Callable

import requests

from models import Match
from parser_v2 import build_match, parse_fixtures, parse_match_card

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


def _match_card_url(match_id: str) -> str:
    return f"{BASE_URL}/{LEAGUE}/Results/MatchCard?matchId={match_id}"


# The top tier arrived with the 2026/27 restructure. Earlier seasons ran seven
# divisions and have no Premier page, so probing for one would only 404.
PREMIER_FROM_SEASON = "2026-27"

# Which Premier slug the site actually serves is not documented, so it is
# found by trying candidates. Remembered per season so the probe runs once.
_premier_slug: dict[str, str | None] = {}


def _find_premier_slug(season: str) -> str | None:
    """The slug the site serves the top tier under, or None if there is none."""
    if season in _premier_slug:
        return _premier_slug[season]

    found = None
    for slug in PREMIER_SLUGS:
        try:
            _fetch_html(_fixtures_url(slug, season))
        except requests.HTTPError:
            continue
        except Exception:
            # A transport failure says nothing about whether the slug is
            # right, so do not remember a None that a retry would fix.
            return None
        finally:
            time.sleep(REQUEST_DELAY)
        found = slug
        break

    _premier_slug[season] = found
    return found


def division_slugs(season: str) -> list[tuple[str, int]]:
    """(url slug, division number) for a season's divisions, top tier first."""
    slugs = [(name, DIVISION_NUMBER[name]) for name in DIVISION_NAMES]
    if season >= PREMIER_FROM_SEASON:
        premier = _find_premier_slug(season)
        if premier:
            slugs.insert(0, (premier, PREMIER_DIVISION))
    return slugs


def scrape_division_page(
    division_name: str,
    division: int,
    season: str,
    known: set[tuple[str, str]] | None = None,
) -> list[Match]:
    """Fetch and parse one division's results for one season.

    The fixtures page gives only the aggregate score, so each played fixture's
    match card is fetched for the individual results. That is a request per
    fixture, so *known* — (season, match_id) pairs already cached — skips the
    ones already held, which is what makes an update run cheap.
    """
    html = _fetch_html(_fixtures_url(division_name, season))
    fixtures = parse_fixtures(html, season)

    matches: list[Match] = []
    for fixture in fixtures:
        match_id = fixture.get("match_id")
        if not match_id:
            # No card to fetch and nothing to deduplicate on, so the result
            # could never be merged. Skip it rather than cache a half-match.
            continue
        if known and (season, match_id) in known:
            continue

        try:
            card = parse_match_card(_fetch_html(_match_card_url(match_id)))
        except requests.HTTPError as e:
            print(f"    match {match_id}: card unavailable ({e})")
            continue
        finally:
            time.sleep(REQUEST_DELAY)

        if card is None:
            print(f"    match {match_id}: card did not parse")
            continue

        match = build_match(fixture, card, division=division, season=season)
        if match and match.played:
            matches.append(match)

    return matches


def scrape_season(
    season: str,
    verbose: bool = True,
    progress: Callable[[str, int, int, int | None, str | None], None] | None = None,
    known: set[tuple[str, str]] | None = None,
) -> list[Match]:
    """Fetch and parse results for every division of one season."""
    all_matches: list[Match] = []
    slugs = division_slugs(season)
    total = len(slugs)

    for div_name, div_num in slugs:
        url = _fixtures_url(div_name, season)
        label = "Premier" if div_num == PREMIER_DIVISION else f"Division {div_num}"
        if verbose:
            print(f"Fetching {season} {label} ({div_name})… ", end="", flush=True)

        try:
            matches = scrape_division_page(div_name, div_num, season, known=known)
            all_matches.extend(matches)
            if verbose:
                print(f"{len(matches)} new match(es) parsed.")
            if progress:
                progress(season, div_num, total, len(matches), None)
        except requests.HTTPError as e:
            # A season whose pages are not up yet 404s; that is not an error
            # worth shouting about, just nothing to fetch.
            note = "not published yet" if e.response is not None and e.response.status_code == 404 else str(e)
            print(f"{label} ({season}): {note}")
            if progress:
                progress(season, div_num, total, None, note)
        except Exception as e:
            print(f"Error fetching {season} {label} ({url}): {type(e).__name__}: {e}")
            if progress:
                progress(season, div_num, total, None, f"{type(e).__name__}: {e}")

        time.sleep(REQUEST_DELAY)

    return all_matches


def scrape_all_divisions(
    verbose: bool = True,
    progress: Callable[[str, int, int, int | None, str | None], None] | None = None,
    seasons: list[str] | None = None,
    known: set[tuple[str, str]] | None = None,
) -> list[Match]:
    """Fetch and parse results for every division of every known season.

    Defaults to every season in SEASONS, so a run picks up both last
    season's completed results and whatever the new one has so far.

    *progress*, if given, is called once per division as
    ``progress(season, division, total_divisions, matches_parsed, error)`` —
    with ``matches_parsed`` None and ``error`` set when that division failed.
    It lets callers (such as the web app) report progress somewhere other
    than stdout while the scrape is still running.

    *known* is the set of (season, match_id) pairs already cached; their match
    cards are not re-fetched.
    """
    all_matches: list[Match] = []
    for season in (seasons or SEASONS):
        all_matches.extend(
            scrape_season(season, verbose=verbose, progress=progress, known=known)
        )
    return all_matches
