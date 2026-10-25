"""Compare the league's own ranking page against these ratings.

The ranking page is saved in a browser like everything else, then:

    uv run python compare_rankings.py /mnt/c/Users/ThroX/Downloads/tt365

Rather than guess at the page's markup, this finds the table whose cells
best match the players we already rate, which also proves it read the right
table. If it cannot, it prints what it did find so the parser can be fixed
against the real thing rather than against an assumption.
"""

import sys
from pathlib import Path

from bs4 import BeautifulSoup

from cache import load_matches
from parser_v2 import parse_fixtures, parse_match_card
from elo import calculate_ratings
from player_identity import identity, load_aliases


def tables(html: str) -> list[list[list[str]]]:
    """Every table as rows of cell text."""
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for table in soup.find_all("table"):
        rows = []
        for tr in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if cells:
                rows.append(cells)
        if len(rows) > 3:
            out.append(rows)
    return out


def name_column(rows: list[list[str]], known: set[str], aliases) -> tuple[int, int]:
    """(column holding player names, how many we recognise in it)."""
    width = max(len(r) for r in rows)
    best, best_hits = 0, 0
    for col in range(width):
        hits = sum(
            1 for r in rows
            if len(r) > col and identity(r[col], aliases) in known
        )
        if hits > best_hits:
            best, best_hits = col, hits
    return best, best_hits


def spearman(pairs: list[tuple[int, int]]) -> float:
    """Rank correlation, computed on the two orderings directly."""
    n = len(pairs)
    if n < 2:
        return 0.0
    mean_a = sum(a for a, _ in pairs) / n
    mean_b = sum(b for _, b in pairs) / n
    cov = sum((a - mean_a) * (b - mean_b) for a, b in pairs)
    va = sum((a - mean_a) ** 2 for a, _ in pairs) ** 0.5
    vb = sum((b - mean_b) ** 2 for _, b in pairs) ** 0.5
    return cov / (va * vb) if va and vb else 0.0


def main(target: str) -> int:
    path = Path(target)
    if path.is_dir():
        pages = [p for p in sorted(path.iterdir())
                 if p.suffix.lower() in (".html", ".htm")]
    else:
        pages = [path]
    if not pages:
        print(f"No saved pages in {path}.")
        return 1

    ratings = calculate_ratings(load_matches() or [])
    known = set(ratings)
    aliases = load_aliases()
    ours = sorted(ratings.values(), key=lambda p: -p.rating)
    our_rank = {pr.player_id: i + 1 for i, pr in enumerate(ours)}

    # A match card is ten rows of player names and would pass any "does this
    # look like a list of players" test, so the pages we can already identify
    # are set aside before looking at all. Then the best candidate wins, not
    # the first one found: a folder holds one ranking page and forty cards.
    best = None
    skipped = 0
    for page in pages:
        html = page.read_text(errors="replace")
        if parse_match_card(html) is not None or parse_fixtures(html):
            skipped += 1
            continue
        for rows in tables(html):
            col, hits = name_column(rows, known, aliases)
            # A ranking lists most of a league, not one team's line-up.
            if hits < 20 or hits < len(rows) // 4:
                continue
            if best is None or hits > best[0]:
                best = (hits, page, rows, col)

    if skipped:
        print(f"Set aside {skipped} fixtures page(s) and match card(s).")
    if best is None:
        print("No ranking table found. What the other pages hold:\n")
        for page in pages:
            html = page.read_text(errors="replace")
            if parse_match_card(html) is not None or parse_fixtures(html):
                continue
            found = tables(html)
            print(f"{page.name}: {len(found)} table(s) over 3 rows")
            for rows in found[:3]:
                col, hits = name_column(rows, known, aliases)
                print(f"  {len(rows)} rows, {hits} known players, "
                      f"first: {rows[0][:6]}")
        return 1

    hits, page, rows, col = best
    print(f"Ranking table in {page.name}:")
    print(f"  {len(rows)} rows, {hits} known players, names in column {col}")
    print(f"  header: {rows[0]}")
    print(f"  sample: {rows[1] if len(rows) > 1 else '-'}\n")
    return report(rows, col, known, aliases, our_rank, ratings)


def report(rows, col, known, aliases, our_rank, ratings) -> int:
    theirs = []
    for row in rows:
        if len(row) <= col:
            continue
        pid = identity(row[col], aliases)
        if pid in known:
            theirs.append(pid)

    seen, order = set(), []
    for pid in theirs:          # keep page order, drop repeats
        if pid not in seen:
            seen.add(pid)
            order.append(pid)

    pairs = [(i + 1, our_rank[pid]) for i, pid in enumerate(order)]
    rho = spearman(pairs)
    print(f"{len(order)} ranked players matched to ours.")
    print(f"Rank correlation (Spearman): {rho:.3f}\n")

    gaps = sorted(
        ((their - our_rank[pid], their, our_rank[pid], pid)
         for their, pid in ((i + 1, p) for i, p in enumerate(order))),
        key=lambda g: g[0],
    )
    def show(label, rows_):
        print(label)
        for diff, their, mine, pid in rows_:
            pr = ratings[pid]
            print(f"  {pr.name:26s} theirs #{their:<4d} ours #{mine:<4d}"
                  f"  {pr.rating:7.1f}  {pr.singles_won}/{pr.singles_played}"
                  f"  {'D' + str(pr.division)}")
        print()

    take = min(8, len(gaps) // 2)
    if take:
        show("Rated far higher by them than by us:", gaps[:take])
        show("Rated far higher by us than by them:",
             list(reversed(gaps[-take:])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
