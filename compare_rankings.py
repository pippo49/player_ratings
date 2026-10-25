"""Compare the league's own ranking page against these ratings.

The ranking page is saved in a browser like everything else, then:

    uv run python compare_rankings.py /mnt/c/Users/ThroX/Downloads/tt365

Rather than guess at the page's markup, this finds the table whose cells
best match the players we already rate, which also proves it read the right
table. If it cannot, it prints what it did find so the parser can be fixed
against the real thing rather than against an assumption.
"""

import re
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


LEADING_INT = re.compile(r"^\s*(\d+)")


def position_column(rows: list[list[str]], name_col: int) -> int | None:
    """The column holding the ranking position, if there is one.

    The ranking paginates, so pages have to be stitched together — and the
    order files happen to be saved in is not the order of the ranking. The
    position printed on each row is, whatever page it came from.
    """
    width = max(len(r) for r in rows)
    for col in range(width):
        if col == name_col:
            continue
        found = [LEADING_INT.match(r[col]) for r in rows[1:] if len(r) > col]
        hits = [int(m.group(1)) for m in found if m]
        # A position column counts: mostly numeric, and distinct values.
        if len(hits) >= len(rows) * 0.8 and len(set(hits)) == len(hits):
            return col
    return None


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
    found_tables = []
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
            found_tables.append((hits, page, rows, col))

    if skipped:
        print(f"Set aside {skipped} fixtures page(s) and match card(s).")
    best = max(found_tables, default=None, key=lambda t: t[0])
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

    # Every ranking page found, stitched into one list by the position each
    # row carries, so saving them in any order works.
    header = best[2][0]
    merged: dict[int, list[str]] = {}
    unplaced: list[list[str]] = []
    for hits, page, rows, col in found_tables:
        pos_col = position_column(rows, col)
        print(f"  {page.name}: {len(rows) - 1} rows, {hits} known players")
        for row in rows[1:]:
            match = (LEADING_INT.match(row[pos_col])
                     if pos_col is not None and len(row) > pos_col else None)
            if match:
                merged.setdefault(int(match.group(1)), row)
            else:
                unplaced.append(row)

    ordered = [merged[k] for k in sorted(merged)] + unplaced
    name_col = best[3]
    print(f"\n{len(found_tables)} ranking page(s) -> {len(ordered)} ranked rows")
    print(f"  header: {header}")
    print(f"  sample: {ordered[0] if ordered else '-'}\n")
    return report([header] + ordered, name_col, known, aliases, our_rank, ratings)


def report(rows, col, known, aliases, our_rank, ratings) -> int:
    theirs, missing_names = [], []
    for row in rows[1:]:          # skip the header
        if len(row) <= col:
            continue
        cell = row[col].strip()
        if not cell:
            continue
        pid = identity(cell, aliases)
        if pid in known:
            theirs.append(pid)
        elif " " in cell:         # looks like a name, but not one we know
            missing_names.append(cell)
    unmatched = len(missing_names)

    seen, order = set(), []
    for pid in theirs:          # keep page order, drop repeats
        if pid not in seen:
            seen.add(pid)
            order.append(pid)

    pairs = [(i + 1, our_rank[pid]) for i, pid in enumerate(order)]

    # What the comparison actually covers. A correlation over the overlap
    # says nothing about either list's remainder, and the two lists are
    # different populations: theirs may be capped or paginated, ours holds
    # everyone who has ever appeared in a result.
    ours_absent = [pr for pid, pr in ratings.items() if pid not in set(order)]
    print(f"Coverage: {len(rows) - 1} rows on their page, "
          f"{len(order)} matched to ours, {unmatched} of theirs unrecognised.")
    print(f"          {len(ratings)} players rated here, "
          f"{len(ours_absent)} of them not on their page.")
    if unmatched:
        print(f"\n  On their page, unknown to us — spelling differences here "
              f"would be splitting a player's record in two:")
        for name in missing_names[:12]:
            print(f"    {name}")
        if unmatched > 12:
            print(f"    ...and {unmatched - 12} more")
    strong = sorted((p for p in ours_absent if p.singles_played >= 15),
                    key=lambda p: -p.rating)[:8]
    if strong:
        print(f"\n  Rated here but not on their page (15+ singles):")
        for pr in strong:
            print(f"    {pr.name:26s} {pr.rating:7.1f}  "
                  f"{pr.singles_won}/{pr.singles_played}  D{pr.division}")
    print()
    print(f"Rank correlation, all matched players: {spearman(pairs):.3f}")

    # Where the two disagree, the question is whether it is substance or
    # small samples: our seeding puts a new player at their division's level
    # and holds them there until results say otherwise, which looks stubborn
    # over three matches and sensible over thirty.
    settled = [(i + 1, our_rank[pid]) for i, pid in enumerate(order)
               if ratings[pid].singles_played >= 15]
    thin = [(i + 1, our_rank[pid]) for i, pid in enumerate(order)
            if ratings[pid].singles_played < 15]
    if settled:
        print(f"  ...15+ singles played ({len(settled)}): "
              f"{spearman(settled):.3f}")
    if thin:
        print(f"  ...fewer than 15 ({len(thin)}):      "
              f"{spearman(thin):.3f}")
    print()

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

    # The same, among players neither system is guessing about. These are
    # the disagreements worth defending; the rest are sample size.
    firm = [g for g in gaps if ratings[g[3]].singles_played >= 15]
    take = min(6, len(firm) // 2)
    if take:
        print("Among players with 15+ singles — the real disagreements\n")
        show("  Higher by them:", firm[:take])
        show("  Higher by us:", list(reversed(firm[-take:])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
