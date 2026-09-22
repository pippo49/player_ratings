"""Parsers for the 2026/27 site redesign.

The old markup (div.home, div.playerName, a "(n)" score) is gone. Fixtures now
live in `table.tt-fixture-table` rows, and each played fixture links to
`/Results/MatchCard?matchId=…` which lists every rubber individually — who
played whom, the game scores, and who won.

That is richer than the old pages, which only gave each player's win count.
The Match model is unchanged, so the individual rubbers are aggregated back
into per-player singles wins: that keeps the rating engine untouched and lets
the new parser be checked against the 937 matches the old one already parsed.
"""

import re
from datetime import date, datetime

from bs4 import BeautifulSoup

from models import Match, PlayerResult, TeamResult

MATCH_ID = re.compile(r"matchId=(\d+)")
SCORE = re.compile(r"(\d+)\s*[-–]\s*(\d+)")

# "Sat 27 Sep 2025", "27/09/2025" — the site has used both.
DATE_FORMATS = ("%a %d %b %Y", "%d %b %Y", "%d/%m/%Y", "%Y-%m-%d")


def _parse_date(text: str) -> date | None:
    cleaned = " ".join(text.split())
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    # Fall back to any embedded ISO date.
    iso = re.search(r"(\d{4}-\d{2}-\d{2})", cleaned)
    return date.fromisoformat(iso.group(1)) if iso else None


def parse_fixtures(html: str) -> list[dict]:
    """Played fixtures on a division's fixtures page.

    Returns {match_id, date, home, away, home_score, away_score} for each
    fixture that has a score. Unplayed fixtures are listed too, with an empty
    score, and are skipped.
    """
    soup = BeautifulSoup(html, "html.parser")
    fixtures = []

    for row in soup.find_all("tr"):
        teams = row.find_all("td", class_="tt-fixture-teamcell")
        score_cell = row.find("td", class_="tt-fixture-score")
        if len(teams) != 2 or score_cell is None:
            continue

        score = SCORE.search(score_cell.get_text())
        if not score:
            continue  # not played yet

        link = score_cell.find("a", href=MATCH_ID)
        if link is None:
            link = row.find("a", href=MATCH_ID)
        match_id = MATCH_ID.search(link["href"]).group(1) if link else ""

        date_cell = row.find("td", class_="tt-fixture-date")
        fixtures.append({
            "match_id": match_id,
            "date": _parse_date(date_cell.get_text()) if date_cell else None,
            "home": teams[0].get_text(strip=True),
            "away": teams[1].get_text(strip=True),
            "home_score": int(score.group(1)),
            "away_score": int(score.group(2)),
        })
    return fixtures


def _names(cell) -> list[str]:
    """Player names in a match-card cell — two of them on the doubles row."""
    links = cell.find_all("a", class_="tt-player-link") or cell.find_all("a")
    if links:
        return [a.get_text(strip=True) for a in links if a.get_text(strip=True)]
    text = cell.get_text(" ", strip=True)
    return [text] if text else []


def parse_match_card(html: str) -> dict | None:
    """Every rubber on a match card, as individual results.

    Returns {home, away, home_score, away_score, rubbers}, where each rubber is
    {home: [names], away: [names], home_won: bool, doubles: bool}.
    """
    soup = BeautifulSoup(html, "html.parser")

    home_el = soup.find(class_="tt-matchcard-team-home")
    away_el = soup.find(class_="tt-matchcard-team-away")
    home_score_el = soup.find(class_="tt-matchcard-score-home")
    away_score_el = soup.find(class_="tt-matchcard-score-away")
    if not (home_el and away_el):
        return None

    rubbers = []
    for row in soup.find_all("tr"):
        players = row.find_all("td", class_="tt-matchcard-col-player")
        score_cell = row.find("td", class_="tt-matchcard-col-score")
        if len(players) != 2 or score_cell is None:
            continue

        score = SCORE.search(score_cell.get_text())
        if not score:
            continue

        home_names, away_names = _names(players[0]), _names(players[1])
        if not home_names or not away_names:
            continue

        rubbers.append({
            "home": home_names,
            "away": away_names,
            "home_won": int(score.group(1)) > int(score.group(2)),
            # A pair on each side is the doubles, which is not attributed to
            # individuals — the rating engine rates singles only.
            "doubles": len(home_names) > 1 or len(away_names) > 1,
        })

    def _score(el) -> int:
        m = SCORE.search(el.get_text()) if el else None
        if m:
            return int(m.group(1))
        digits = re.search(r"\d+", el.get_text()) if el else None
        return int(digits.group()) if digits else 0

    return {
        "home": home_el.get_text(strip=True),
        "away": away_el.get_text(strip=True),
        "home_score": _score(home_score_el),
        "away_score": _score(away_score_el),
        "rubbers": rubbers,
    }


def build_match(fixture: dict, card: dict, division: int, season: str) -> Match | None:
    """Fold a match card's rubbers back into the Match model.

    Each player's `games_won` is their singles wins, as the old pages gave
    directly. The doubles is excluded from that count but still included in
    the team total, which is what the 10-point score reflects.
    """
    singles = [r for r in card["rubbers"] if not r["doubles"]]
    if not singles:
        return None

    home_wins: dict[str, int] = {}
    away_wins: dict[str, int] = {}
    for rubber in singles:
        home, away = rubber["home"][0], rubber["away"][0]
        home_wins.setdefault(home, 0)
        away_wins.setdefault(away, 0)
        if rubber["home_won"]:
            home_wins[home] += 1
        else:
            away_wins[away] += 1

    def side(name: str, wins: dict[str, int], total: int) -> TeamResult:
        return TeamResult(
            name=name,
            players=[
                # No stable id in the card, so the name carries identity —
                # which is what crosses seasons anyway, since ids are reissued.
                PlayerResult(name=player, player_id=player, games_won=won)
                for player, won in wins.items()
            ],
            total_score=total,
        )

    return Match(
        division=division,
        date=fixture.get("date"),
        season=season,
        match_id=fixture.get("match_id") or "",
        home=side(card["home"], home_wins, card["home_score"]),
        away=side(card["away"], away_wins, card["away_score"]),
    )
