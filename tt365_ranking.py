"""The league's own ranking pages, as saved in a browser.

The ranking is the one page that carries a rating for every active player,
which is what makes a three-page weekly update possible: without it the
individual results have to come from one match card per fixture, forty a
week. It paginates, so there are two or three pages.

Nothing here guesses at the markup. The ranking table is found by looking for
the table whose cells match the most players we already know, which both
locates it and proves it read the right one — a match card is ten rows of
real player names and would pass any looser test.

    from tt365_ranking import parse_folder
    ranking = parse_folder(Path("~/tt365"), known_player_ids)
"""

import re
from pathlib import Path

from bs4 import BeautifulSoup

from parser_v2 import parse_fixtures, parse_match_card
from player_identity import identity, load_aliases

LEADING_INT = re.compile(r"^\s*(\d+)")
PLAIN_INT = re.compile(r"^\s*([+-]?\d{1,5})\s*$")

# Columns worth keeping, by the heading the page gives them.
WANTED = {"current": "current", "provisional": "provisional",
          "month +/-": "month", "season +/-": "season"}


def tables(html: str) -> list[list[list[str]]]:
    """Every table of more than three rows, as rows of cell text."""
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for table in soup.find_all("table"):
        rows = [[c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
                for tr in table.find_all("tr")]
        rows = [r for r in rows if r]
        if len(rows) > 3:
            out.append(rows)
    return out


def name_column(rows, known, aliases) -> tuple[int, int]:
    """(column holding player names, how many we recognise in it)."""
    width = max(len(r) for r in rows)
    best, best_hits = 0, 0
    for col in range(width):
        hits = sum(1 for r in rows
                   if len(r) > col and identity(r[col], aliases) in known)
        if hits > best_hits:
            best, best_hits = col, hits
    return best, best_hits


def position_column(rows, name_col) -> int | None:
    """The column holding the ranking position, if there is one.

    Pages are stitched together by it: a browser names saved files however it
    likes, and the ranking's own numbering is the one ordering certain to be
    right.
    """
    width = max(len(r) for r in rows)
    for col in range(width):
        if col == name_col:
            continue
        hits = [int(m.group(1)) for m in
                (LEADING_INT.match(r[col]) for r in rows[1:] if len(r) > col)
                if m]
        if len(hits) >= len(rows) * 0.8 and len(set(hits)) == len(hits):
            return col
    return None


def parse_folder(folder: Path, known: set[str]) -> dict[str, dict]:
    """{player id: {position, current, provisional, month, season}}.

    Every ranking page in the folder, merged. Fixtures pages and match cards
    are set aside first, since a card would otherwise look like a short
    ranking.
    """
    aliases = load_aliases()
    found = []
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() not in (".html", ".htm"):
            continue
        html = path.read_text(errors="replace")
        if parse_match_card(html) is not None or parse_fixtures(html):
            continue
        for rows in tables(html):
            col, hits = name_column(rows, known, aliases)
            if hits >= 20 and hits >= len(rows) // 4:
                found.append((rows, col))

    out: dict[str, dict] = {}
    for rows, col in found:
        pos_col = position_column(rows, col)
        headings = {i: WANTED[h.strip().lower()]
                    for i, h in enumerate(rows[0])
                    if h.strip().lower() in WANTED}
        for row in rows[1:]:
            if len(row) <= col:
                continue
            pid = identity(row[col], aliases)
            if not pid or pid in out:
                continue
            entry = {}
            if pos_col is not None and len(row) > pos_col:
                m = LEADING_INT.match(row[pos_col])
                if m:
                    entry["position"] = int(m.group(1))
            for i, key in headings.items():
                if len(row) > i:
                    m = PLAIN_INT.match(row[i])
                    if m:
                        entry[key] = int(m.group(1))
            if "current" in entry or "provisional" in entry:
                entry["name"] = row[col].strip()
                out[pid] = entry
    return out
