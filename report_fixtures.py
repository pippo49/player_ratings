"""Report a season's published fixture list, played or not.

parser_v2.parse_fixtures deliberately skips fixtures with no score — it feeds
the rating engine, which only cares about results. A captain cares about the
schedule before it is played, and the fixture list is also the honest answer
to which teams are actually entered: a team that withdrew after registering
appears in the team map but in nobody's fixtures.

    .venv/bin/python3 report_fixtures.py 2026-27 Division_Four "Apex 4"

Prints to stdout rather than writing a file: this is a diagnostic, run from a
GitHub Actions job whose log is the only channel out.
"""

import sys
from datetime import date

from bs4 import BeautifulSoup

from parser_v2 import MATCH_ID, SCORE, _parse_date
from scraper import _fetch_html, _fixtures_url


def parse_all_fixtures(html: str) -> list[dict]:
    """Every fixture on the page. Unplayed ones carry scores of None."""
    soup = BeautifulSoup(html, "html.parser")
    fixtures = []

    for row in soup.find_all("tr"):
        teams = row.find_all("td", class_="tt-fixture-teamcell")
        score_cell = row.find("td", class_="tt-fixture-score")
        if len(teams) != 2 or score_cell is None:
            continue

        score = SCORE.search(score_cell.get_text())
        link = score_cell.find("a", href=MATCH_ID) or row.find("a", href=MATCH_ID)
        date_cell = row.find("td", class_="tt-fixture-date")
        raw_date = date_cell.get_text(" ", strip=True) if date_cell else ""
        fixtures.append({
            "match_id": MATCH_ID.search(link["href"]).group(1) if link else "",
            "date": _parse_date(raw_date) if raw_date else None,
            "raw_date": raw_date,
            "home": teams[0].get_text(strip=True),
            "away": teams[1].get_text(strip=True),
            "home_score": int(score.group(1)) if score else None,
            "away_score": int(score.group(2)) if score else None,
            "row": row,
        })
    return fixtures


def dump(fixture: dict) -> None:
    """Every cell of one fixture row, for when the parse looks wrong."""
    for cell in fixture["row"].find_all("td"):
        classes = " ".join(cell.get("class", []))
        text = " ".join(cell.get_text(" ", strip=True).split())[:60]
        print(f"      [{classes:26}] {text!r}")


def main() -> None:
    season = sys.argv[1] if len(sys.argv) > 1 else "2026-27"
    division = sys.argv[2] if len(sys.argv) > 2 else "Division_Four"
    team = sys.argv[3] if len(sys.argv) > 3 else None

    url = _fixtures_url(division, season)
    print(f"{season} — {division}\n  {url}")
    fixtures = parse_all_fixtures(_fetch_html(url))
    played = [f for f in fixtures if f["home_score"] is not None]

    teams = sorted({f["home"] for f in fixtures} | {f["away"] for f in fixtures})
    print(f"  {len(fixtures)} fixtures, {len(played)} played, {len(teams)} teams")

    # A full double round robin is n(n-1) fixtures. A mismatch means byes, a
    # withdrawal mid-schedule, or a division that is not a round robin.
    expected = len(teams) * (len(teams) - 1)
    if len(fixtures) != expected:
        print(f"  NOTE: {expected} expected for a double round robin of {len(teams)}")

    # Dates drive the whole point of a fixture list, so a format the parser
    # does not know must be loud rather than silently None.
    undated = [f for f in fixtures if f["date"] is None]
    if undated:
        samples = sorted({f["raw_date"] for f in undated})[:4]
        print(f"  WARNING: {len(undated)} fixtures with an unparsed date")
        print(f"    date cell reads: {samples}")

    print("\n  teams entered (home / away):")
    for name in teams:
        h = sum(1 for f in fixtures if f["home"] == name)
        a = sum(1 for f in fixtures if f["away"] == name)
        flag = "  <- not balanced" if h != a else ""
        print(f"    {name:34s} {h:>2} / {a:<2}{flag}")

    # In a double round robin every pair meets once each way. A pair that
    # meets twice the same way means a row was read with its teams the wrong
    # way round, or the schedule is not what it looks like.
    from collections import Counter
    pairs = Counter((f["home"], f["away"]) for f in fixtures)
    odd = [p for p, n in pairs.items() if n > 1 or pairs[(p[1], p[0])] != 1]
    if odd:
        print(f"\n  {len(odd)} pairings are not one-each-way:")
        for home, away in sorted(odd)[:6]:
            print(f"    {home} v {away}  "
                  f"(this way {pairs[(home, away)]}, reverse {pairs[(away, home)]})")
        suspect = next(f for f in fixtures if (f["home"], f["away"]) == sorted(odd)[0])
        print("\n  that fixture's row, cell by cell:")
        dump(suspect)

    if played:
        print("\n  results so far:")
        for f in sorted(played, key=lambda f: (f["date"] or date.min)):
            print(f"    {f['date']}  {f['home']:28s} {f['home_score']:>2}-"
                  f"{f['away_score']:<2} {f['away']}  (match {f['match_id']})")

    if team:
        mine = [f for f in fixtures if team_in(f, team)]
        print(f"\n  {team} — {len(mine)} fixtures:")
        if not mine:
            print("    none. Check the spelling against the list above.")
        for f in sorted(mine, key=lambda f: (f["date"] or date.min)):
            at = "H" if f["home"] == team else "A"
            opponent = f["away"] if at == "H" else f["home"]
            if f["home_score"] is None:
                result = ""
            elif at == "H":
                result = f"  {f['home_score']}-{f['away_score']}"
            else:
                result = f"  {f['away_score']}-{f['home_score']}"
            print(f"    {f['date']}  {at}  {opponent:30s}{result}")


def team_in(fixture: dict, name: str) -> bool:
    return name in (fixture["home"], fixture["away"])


if __name__ == "__main__":
    main()
