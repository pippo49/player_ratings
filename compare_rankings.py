"""Compare the league's own ranking page against these ratings.

The ranking page is saved in a browser like everything else, then:

    uv run python compare_rankings.py /mnt/c/Users/ThroX/Downloads/tt365

Rather than guess at the page's markup, this finds the table whose cells
best match the players we already rate, which also proves it read the right
table. If it cannot, it prints what it did find so the parser can be fixed
against the real thing rather than against an assumption.
"""

import random
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

from cache import load_matches
from parser_v2 import parse_fixtures, parse_match_card
from elo import calculate_ratings
from player_identity import identity, load_aliases
from scraper import CURRENT_SEASON


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


def predict(their_rank: dict[str, int], aliases) -> None:
    """Which ordering better calls the results, rather than merely agreeing.

    A correlation says how much two rankings agree, not which is right. Each
    player meets three opponents in a match, so a ranking predicts how many
    of them they beat: the ones it places below them. Comparing that with
    what happened scores both orderings on the same results.

    Ours is rated on last season alone, so this season is genuinely unseen.
    Theirs is a current ranking that already includes these results. The
    comparison is therefore tilted their way, which is the right direction
    for it to be tilted: a tie means ours did as well on harder terms.
    """
    from elo import calculate_ratings
    from models import real_singles

    matches = load_matches() or []
    past = [m for m in matches if m.season != CURRENT_SEASON]
    now = [m for m in matches if m.season == CURRENT_SEASON]
    if not past or not now:
        return

    before = calculate_ratings(past)
    our_rank = {pid: i + 1 for i, pr in enumerate(
        sorted(before.values(), key=lambda p: -p.rating)) for pid in [pr.player_id]}

    # A shuffled ordering, so the two scores can be read against what
    # knowing nothing would get. Seeded, so the figure does not wander
    # between runs.
    shuffled = list(our_rank)
    random.Random(0).shuffle(shuffled)
    chance_rank = {pid: i + 1 for i, pid in enumerate(shuffled)}

    ours_error = theirs_error = chance_error = 0.0
    scored = 0
    for match in now:
        singles = real_singles(match)
        for side, other in ((match.home, match.away), (match.away, match.home)):
            for player in side.players:
                me = identity(player.name, aliases)
                opponents = [identity(o.name, aliases) for o in other.players]
                if me not in our_rank or me not in their_rank:
                    continue
                usable = [o for o in opponents
                          if o in our_rank and o in their_rank and o != me]
                if not usable:
                    continue
                actual, _ = singles[player.player_id]
                # Lower rank number is better, so "below me" is a larger one.
                ours_said = sum(1 for o in usable if our_rank[o] > our_rank[me])
                theirs_said = sum(1 for o in usable if their_rank[o] > their_rank[me])
                # Scale the actual to the pairings both systems could judge.
                share = actual * len(usable) / max(1, len(opponents))
                chance_said = sum(1 for o in usable
                                  if chance_rank[o] > chance_rank[me])
                ours_error += abs(ours_said - share)
                theirs_error += abs(theirs_said - share)
                chance_error += abs(chance_said - share)
                scored += 1

    if not scored:
        print("\nNo pairings this season have both players in both systems.")
        return
    print(f"\nCalling this season's results ({scored} player-matches, "
          "ours rated on last\nseason only, theirs already including them):")
    print(f"  average error, ours:    {ours_error / scored:.3f} wins out of 3")
    print(f"  average error, theirs:  {theirs_error / scored:.3f}")
    print(f"  average error, shuffled:{chance_error / scored:7.3f}")
    better = "ours" if ours_error < theirs_error else "theirs"
    gap = abs(ours_error - theirs_error) / scored
    print(f"  {better} closer by {gap:.3f} per player-match\n")


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

    # If the two agree within each division but disagree between them, the
    # difference is the seeding ladder — an assumption, not a measurement —
    # rather than any judgement about individual players. That is a very
    # different thing to tell someone, so it is worth measuring.
    by_division: dict[int, list[tuple[int, int, str]]] = {}
    for i, pid in enumerate(order):
        pr = ratings[pid]
        if pr.division is not None:
            by_division.setdefault(pr.division, []).append(
                (i + 1, our_rank[pid], pid))

    n_theirs, n_ours = len(order), len(ratings)
    print("Within each division, and where each division sits overall:\n")
    print(f"  {'div':>5} {'players':>8} {'agreement':>10} "
          f"{'their median':>13} {'our median':>11}  {'shift':>6}")
    for div in sorted(by_division):
        rows_ = by_division[div]
        if len(rows_) < 5:
            continue
        rho = spearman([(a, b) for a, b, _ in rows_])
        mid = len(rows_) // 2
        their_pct = sorted(a / n_theirs for a, _, _ in rows_)[mid] * 100
        our_pct = sorted(b / n_ours for _, b, _ in rows_)[mid] * 100
        name = "Prem" if div == 0 else f"D{div}"
        print(f"  {name:>5} {len(rows_):>8} {rho:>10.3f} "
              f"{their_pct:>12.0f}% {our_pct:>10.0f}%  "
              f"{our_pct - their_pct:>+5.0f}")
    print("\n  A negative shift means we place that division higher than they do."
          "\n  Agreement is the rank correlation among that division's players"
          "\n  alone, which the seeding ladder cannot affect.\n")

    take = min(8, len(gaps) // 2)
    if take:
        show("Rated far higher by them than by us:", gaps[:take])
        show("Rated far higher by us than by them:",
             list(reversed(gaps[-take:])))

    # The same, among players neither system is guessing about. These are
    # the disagreements worth defending; the rest are sample size.
    predict({pid: i + 1 for i, pid in enumerate(order)}, aliases)

    firm = [g for g in gaps if ratings[g[3]].singles_played >= 15]
    take = min(6, len(firm) // 2)
    if take:
        print("Among players with 15+ singles — the real disagreements\n")
        show("  Higher by them:", firm[:take])
        show("  Higher by us:", list(reversed(firm[-take:])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
