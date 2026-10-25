"""What rating gap actually means a given chance of winning.

The engine updates ratings with Elo's constant of 400. Whether that is also
the right constant for *forecasting* is a separate question with a
measurable answer: rate on last season, then see which constant best
describes this one.

Scored two ways, both proper:

  * the observed win rate bucketed by rating gap, which assumes nothing;
  * a Brier score over every pairing.

Not by mean absolute error on wins out of three. That is not a proper
scoring rule — if the true chance is 0.7, predicting certainty scores 0.30
against 0.42 for predicting 0.7 — so it pays for overconfidence, and fitting
to it once drove this constant to 120, less than half its real value.

    uv run python fit_scale.py
"""

import sys
from collections import defaultdict

import elo
from cache import load_matches
from models import real_singles
from player_identity import identity


def main() -> int:
    matches = load_matches() or []
    past = [m for m in matches if m.season != elo_season(matches)]
    now = [m for m in matches if m.season == elo_season(matches)]
    if not past or not now:
        print("Need a previous season to rate from and a current one to test.")
        return 1

    rated = elo.calculate_ratings(past)
    pairs = []
    for m in now:
        singles = real_singles(m)
        for side, other in ((m.home, m.away), (m.away, m.home)):
            for p in side.players:
                me = identity(p.name)
                opp = [identity(o.name) for o in other.players]
                if me not in rated or not all(o in rated for o in opp):
                    continue
                won, played = singles[p.player_id]
                if not played:
                    continue
                for o in opp:
                    pairs.append((rated[me].rating - rated[o].rating,
                                  won / len(opp)))

    print(f"{len(pairs)} pairings, ratings from the previous season\n")

    def brier(scale: float) -> float:
        return sum((1 / (1 + 10 ** (-g / scale)) - a) ** 2
                   for g, a in pairs) / len(pairs)

    best = min(range(60, 1001, 5), key=lambda s: brier(float(s)))
    print(f"{'scale':>7} {'Brier':>8}  (lower is better)")
    for s in sorted({95, 150, 200, 250, 300, 400, best}):
        tag = "   <- in use" if s == int(elo.PREDICTION_SCALE) else ""
        tag = tag or ("   <- best" if s == best else "")
        print(f"{s:>7} {brier(float(s)):>8.4f}{tag}")

    buckets = defaultdict(lambda: [0.0, 0])
    for gap, actual in pairs:
        b = buckets[int(gap // 50) * 50]
        b[0] += actual
        b[1] += 1
    print(f"\n{'gap':>14} {'n':>5} {'actual':>8} {'fitted':>8}")
    for lo in sorted(buckets):
        total, n = buckets[lo]
        if n < 12:
            continue
        mid = lo + 25
        print(f"{lo:>6} to {lo + 50:<6} {n:>5} {total / n:>8.2f} "
              f"{1 / (1 + 10 ** (-mid / best)):>8.2f}")
    print(f"\nbest fit {best}; elo.PREDICTION_SCALE is "
          f"{elo.PREDICTION_SCALE:.0f}")
    return 0


def elo_season(matches) -> str:
    return max(m.season for m in matches)


if __name__ == "__main__":
    sys.exit(main())
