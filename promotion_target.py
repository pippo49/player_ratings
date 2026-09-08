"""What points-per-match actually wins a division, from past results.

A team match is worth 10 points, so a season target is best expressed as
points per match. This works out what the teams that finished 1st and 2nd
actually averaged in each division, which is a far better guide than
guessing at a round number.

    .venv/bin/python3 promotion_target.py
    .venv/bin/python3 promotion_target.py 5      # just division 5
"""

import sys
from collections import defaultdict

from cache import load_matches
from models import Match

POINTS_PER_MATCH = 10


def standings(matches: list[Match], season: str, division: int) -> list[tuple[str, int, int]]:
    """Return [(team, points, matches_played)] for one division, best first."""
    points: dict[str, int] = defaultdict(int)
    played: dict[str, int] = defaultdict(int)

    for m in matches:
        if m.season != season or m.division != division:
            continue
        for side in (m.home, m.away):
            points[side.name] += side.total_score
            played[side.name] += 1

    table = [(team, points[team], played[team]) for team in points]
    # Rank on points per match, so a team with games in hand is not punished.
    table.sort(key=lambda row: row[1] / row[2] if row[2] else 0, reverse=True)
    return table


def report(matches: list[Match], only: int | None = None) -> None:
    seasons = sorted({m.season for m in matches})
    divisions = sorted({m.division for m in matches})

    for season in seasons:
        print(f"\n{'=' * 74}\n  {season} — what it took to finish top\n{'=' * 74}")
        print(f"  {'Div':>3} {'teams':>6} {'played':>7} {'1st':>7} {'2nd':>7} {'3rd':>7}   winner")
        print(f"  {'-' * 70}")

        firsts, seconds = [], []
        for division in divisions:
            if only and division != only:
                continue
            table = standings(matches, season, division)
            if len(table) < 3:
                continue

            rates = [(p / n if n else 0) for _, p, n in table]
            firsts.append(rates[0])
            seconds.append(rates[1])
            typical_played = max(n for _, _, n in table)

            print(
                f"  {division:>3} {len(table):>6} {typical_played:>7} "
                f"{rates[0]:>7.2f} {rates[1]:>7.2f} {rates[2]:>7.2f}   {table[0][0]}"
            )

        if firsts and not only:
            print(f"\n  Across {len(firsts)} divisions, points per match out of {POINTS_PER_MATCH}:")
            print(f"    to win the division  : {min(firsts):.2f} – {max(firsts):.2f}"
                  f"   (median {sorted(firsts)[len(firsts) // 2]:.2f})")
            print(f"    to finish 2nd        : {min(seconds):.2f} – {max(seconds):.2f}"
                  f"   (median {sorted(seconds)[len(seconds) // 2]:.2f})")

    if only:
        for season in seasons:
            table = standings(matches, season, only)
            if not table:
                continue
            print(f"\n  Division {only} — {season} final table")
            print(f"  {'':>3} {'team':<28} {'pts':>5} {'played':>7} {'per match':>10}")
            for i, (team, pts, n) in enumerate(table, 1):
                print(f"  {i:>3} {team:<28} {pts:>5} {n:>7} {pts / n if n else 0:>10.2f}")


def _expected(a: float, b: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((b - a) / 400.0))


def project(division: int) -> None:
    """Project a division's table from current ratings.

    Every team is assumed to field its three highest-rated players against
    every other, and to split the doubles evenly — the doubles is not
    modelled, since the data does not record who paired up. The result is
    each team's expected points per match against this season's actual
    field, which is a better guide to what promotion will take than last
    season's table of a different set of teams.
    """
    from webapp.api import build_payload

    payload = build_payload(load_matches())
    players = {p["id"]: p for p in payload["players"]}
    teams = [t for t in payload["teams"] if t["division"] == division]
    if len(teams) < 3:
        print(f"Not enough teams projected into Division {division}.")
        return

    best: dict[str, list[float]] = {}
    for team in teams:
        rated = sorted(
            (players[m["id"]]["rating"] for m in team["players"] if m["id"] in players),
            reverse=True,
        )
        if len(rated) >= 3:
            best[team["name"]] = rated[:3]

    rows = []
    for name, ours in best.items():
        totals = [
            sum(_expected(a, b) for a in ours for b in theirs) + 0.5
            for other, theirs in best.items() if other != name
        ]
        rows.append((name, sum(totals) / len(totals)))
    rows.sort(key=lambda r: r[1], reverse=True)

    print(f"\n{'=' * 74}")
    print(f"  Division {division} — projected on current ratings")
    print("=" * 74)
    print(f"  {len(rows)} teams, each playing the others home and away "
          f"({2 * (len(rows) - 1)} matches)\n")
    print(f"  {'':>3} {'team':<28} {'pts/match':>10}   {'season pts':>10}")
    for i, (name, rate) in enumerate(rows, 1):
        marker = "  <- promotion cut" if i == 2 else ""
        print(f"  {i:>3} {name:<28} {rate:>10.2f}   "
              f"{rate * 2 * (len(rows) - 1):>10.0f}{marker}")

    print(f"\n  To win it      : better than {rows[0][1]:.2f} per match")
    print(f"  To finish top 2: better than {rows[2][1]:.2f} per match "
          f"(what 3rd is projected to average)")


def main() -> None:
    matches = load_matches()
    if not matches:
        print("No cached matches — run `main.py --refresh` first.")
        return
    args = [a for a in sys.argv[1:]]
    if args and args[0] == "--projected":
        project(int(args[1]) if len(args) > 1 else 5)
        return
    only = int(args[0]) if args else None
    report(matches, only)


if __name__ == "__main__":
    main()
