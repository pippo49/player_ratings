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


def rating_columns(rows: list[list[str]], name_col: int,
                   pos_col: int | None) -> list[int]:
    """Every column of plain numbers big enough to be ratings, not counts.

    The page carries more than one — a published figure and a provisional
    one — and they are not equally useful: the ranking is republished
    monthly, so one of them can be weeks behind the results it is meant to
    describe. Which is which is settled by fitting both.
    """
    width = max(len(r) for r in rows)
    found = []
    for col in range(width):
        if col in (name_col, pos_col):
            continue
        values = []
        for row in rows[1:]:
            if len(row) > col:
                m = re.fullmatch(r"\s*(\d{3,5})\s*", row[col])
                if m:
                    values.append(int(m.group(1)))
        if len(values) >= len(rows) * 0.8 and len(set(values)) > 10:
            found.append(col)
    return found


def calibrate(scales: dict[str, dict[str, float]], aliases) -> None:
    """Fit each set of ratings to the results, on one shared set of cases.

    Projecting a team's points needs "rating difference -> chance of
    winning". Their scale is undocumented, so the constant is fitted rather
    than assumed — which also answers whether the scale is usable at all.

    Every rating set is scored on the same player-matches, so the numbers can
    be read against each other. That is the comparison that decides whether
    adopting their ratings would cost anything: the rank test earlier is
    cruder, and a continuous prediction scored against an integer outcome
    carries a floor that rank predictions do not.
    """
    from models import real_singles

    shared = set.intersection(*(set(r) for r in scales.values()))
    cases = []
    for match in load_matches() or []:
        if match.season != CURRENT_SEASON:
            continue
        singles = real_singles(match)
        for side, other in ((match.home, match.away), (match.away, match.home)):
            for player in side.players:
                me = identity(player.name, aliases)
                opponents = [identity(p.name, aliases) for p in other.players]
                if me not in shared or not all(o in shared for o in opponents):
                    continue
                won, played = singles[player.player_id]
                if played:
                    cases.append((me, opponents, won))

    if len(cases) < 50:
        print("\nToo few players rated by everything to calibrate.")
        return

    def error(ratings: dict[str, float] | None, scale: float) -> float:
        """Brier score over each pairing — a proper scoring rule.

        Not mean absolute error on wins out of three, which this used to be.
        MAE pays for overconfidence: at a true chance of 0.7 it scores 0.30
        for predicting certainty against 0.42 for predicting 0.7, so fitting
        to it drives the scale far too low. It did exactly that here.
        """
        total = count = 0.0
        for me, opponents, won in cases:
            share = won / len(opponents)
            for o in opponents:
                p = (0.5 if ratings is None else
                     1 / (1 + 10 ** ((ratings[o] - ratings[me]) / scale)))
                total += (p - share) ** 2
                count += 1
        return total / count

    def buckets(ratings: dict[str, float], width: int) -> list[tuple]:
        """Observed win rate by rating gap — the shape of a scale itself.

        A rating list claims, implicitly, that a gap of a given size means
        the same thing everywhere along it. Counting how often the stronger
        player actually won, grouped by gap, is how that claim is checked,
        and it needs nobody to have published a probability.
        """
        got: dict[int, list] = {}
        for me, opponents, won in cases:
            for o in opponents:
                gap = ratings[me] - ratings[o]
                row = got.setdefault(int(gap // width) * width, [0.0, 0])
                row[0] += won / len(opponents)
                row[1] += 1
        return [(lo, total / n, n) for lo, (total, n) in sorted(got.items())
                if n >= 20]

    grid = list(range(60, 3001, 10))
    print(f"\nFitted on {len(cases)} player-matches rated by all of them,"
          f"\nscored by Brier (a proper rule; lower is better):")
    print(f"  {'ratings':<28} {'best scale':>10} {'Brier':>7}")
    for label, ratings in scales.items():
        best = min(grid, key=lambda sc: error(ratings, float(sc)))
        edge = " (edge of search)" if best in (grid[0], grid[-1]) else ""
        print(f"  {label:<28} {best:>10} "
              f"{error(ratings, float(best)):>7.4f}{edge}")
    print(f"  {'ignoring ratings entirely':<28} {'-':>10} "
          f"{error(None, 1):>7.4f}")
    print("  Elo's own constant is 400; fitted here, ours is 250.\n")

    # The same table for each list, in its own units. This is the part worth
    # showing the league: it says whether their own gaps behave consistently,
    # and it stands without anyone having published a probability.
    for label, ratings in scales.items():
        spread = max(ratings.values()) - min(ratings.values())
        width = max(10, int(round(spread / 30 / 10)) * 10)
        rows = buckets(ratings, width)
        if len(rows) < 3:
            continue
        fit = min(grid, key=lambda sc: error(ratings, float(sc)))
        print(f"\n  {label} — observed win rate by gap "
              f"(buckets of {width}):")
        print(f"    {'gap':>16} {'pairings':>9} {'won':>6} {'fitted':>7}")
        for lo, rate, n in rows:
            fitted = 1 / (1 + 10 ** (-(lo + width / 2) / fit))
            print(f"    {lo:>7} to {lo + width:<6} {n:>9} {rate:>5.0%} "
                  f"{fitted:>7.0%}")
    print()


def describe_their_model(rows, name_col, pos_col, aliases, known) -> None:
    """The shape of their scale: where it starts, ends, and how fast it moves.

    Comparing two rating systems needs more than a correlation — what a point
    is worth differs, so "started at 1200" means nothing without knowing the
    range it sits in or how far a season can carry someone.
    """
    numeric = rating_columns(rows, name_col, pos_col)
    movement = [c for c in range(max(len(r) for r in rows))
                if c not in numeric + [name_col, pos_col]
                and sum(1 for r in rows[1:]
                        if len(r) > c and re.fullmatch(r"\s*[+-]?\d+\s*", r[c]))
                >= len(rows) * 0.8]

    def column(col):
        out = []
        for row in rows[1:]:
            if len(row) > col:
                m = re.fullmatch(r"\s*([+-]?\d+)\s*", row[col])
                if m:
                    out.append(int(m.group(1)))
        return sorted(out)

    def band(values):
        n = len(values)
        pick = lambda q: values[min(n - 1, int(q * n))]
        return (f"{values[0]} to {values[-1]}, "
                f"middle half {pick(0.25)}–{pick(0.75)}, median {pick(0.5)}")

    print("\nThe shape of their scale:")
    for col in numeric:
        label = rows[0][col] if len(rows[0]) > col else str(col)
        values = column(col)
        if values:
            print(f"  {label:<14} {band(values)}")
    for col in movement:
        label = rows[0][col] if len(rows[0]) > col else str(col)
        values = column(col)
        if values:
            moved = [v for v in values if v]
            print(f"  {label:<14} {band(values)}"
                  f"  ({len(moved)} of {len(values)} moved at all)")


def predict(their_rank: dict[str, int], aliases) -> None:
    """Which ordering better calls the results, rather than merely agreeing.

    A correlation says how much two rankings agree, not which is right. Each
    player meets three opponents in a match, so a ranking predicts how many
    of them they beat: the ones it places below them. Comparing that with
    what happened scores both orderings on the same results.

    Mean absolute error is the right measure here and the wrong one for
    fitting a probability: both rankings predict a whole number of wins, so
    neither can be rewarded for false confidence. `calibrate` scores
    probabilities and uses Brier instead.

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

    from elo import calculate_ratings
    scales: dict[str, dict[str, float]] = {}
    for rat_col in rating_columns(rows, col, position_column(rows, col)):
        their_rating = {}
        for row in rows[1:]:
            if len(row) <= max(col, rat_col):
                continue
            m = re.fullmatch(r"\s*(\d{3,5})\s*", row[rat_col])
            pid = identity(row[col], aliases)
            if m and pid in known:
                their_rating.setdefault(pid, float(m.group(1)))
        label = rows[0][rat_col] if len(rows[0]) > rat_col else str(rat_col)
        scales[f"theirs, {label}"] = their_rating

    describe_their_model(rows, col, position_column(rows, col), aliases, known)

    matches = load_matches() or []
    past = [m for m in matches if m.season != CURRENT_SEASON]
    scales["ours, all results"] = {k: v.rating for k, v in ratings.items()}
    if past:
        scales["ours, last season only"] = {
            k: v.rating for k, v in calculate_ratings(past).items()}
    if scales:
        calibrate(scales, aliases)

    firm = [g for g in gaps if ratings[g[3]].singles_played >= 15]
    take = min(6, len(firm) // 2)
    if take:
        print("Among players with 15+ singles — the real disagreements\n")
        show("  Higher by them:", firm[:take])
        show("  Higher by us:", list(reversed(firm[-take:])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "."))
