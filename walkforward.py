"""Predict each match of the current season from only what came before it.

The other evaluations (`fit_scale.py`, `compare_rankings.py`) rate on one
season and predict the next in a block. That is the right test for most of
the model, but it cannot see a start-of-season rule at all: within a single
season a player's career record *is* their season record, so anything
conditioned on "their first few matches of this season" never binds.

Walking forward does see it. Rate on the completed seasons, then step
through the current one in date order — predict a match, then let it update
the ratings. That is what the system actually does in use, and it is the
only test where career and season records differ.

Scored by Brier, as everywhere else: see "How to judge a change to the
ratings" in HANDOFF.md for why mean absolute error will not do.

    python walkforward.py
"""
import random
from datetime import date as _d

import elo
from cache import load_matches
from models import real_singles
from player_identity import identity

CURRENT = "2026-27"
SCALE = 280.0      # refitted inside the sweep; this is the starting point
BOOTSTRAPS = 4000


def _load():
    matches = load_matches() or []
    past = [m for m in matches if m.season != CURRENT]
    now = sorted((m for m in matches if m.season == CURRENT),
                 key=lambda m: m.date or _d.min)
    return past, now


def walk(past, now, settle_floor=0.0, settle_len=0, scale=SCALE):
    """Every squared error, in order, from one pass through the season.

    Returning the individual errors rather than their mean lets two variants
    be compared on the same matches, which is what makes a 300-pairing
    sample say anything at all.
    """
    carried = elo.calculate_ratings(past)
    rating = {p: r.rating for p, r in carried.items()}
    career = {p: r.matches_played for p, r in carried.items()}
    season: dict[str, int] = {}
    errors: list[float] = []

    for m in now:
        home, away = m.home.players, m.away.players
        ids = {p.player_id: identity(p.name) for p in home + away}
        if not all(v in rating for v in ids.values()):
            continue  # nobody can be predicted from a record that is absent
        singles = real_singles(m)

        # Predict first, from ratings that have not seen this match.
        for side, others in ((home, away), (away, home)):
            for p in side:
                me = ids[p.player_id]
                won, played = singles[p.player_id]
                if not played:
                    continue
                share = won / len(others)
                for o in others:
                    gap = rating[me] - rating[ids[o.player_id]]
                    errors.append((1 / (1 + 10 ** (-gap / scale)) - share) ** 2)

        # Then update, both sides from the same pre-match ratings.
        moves = {}
        for side, others in ((home, away), (away, home)):
            for p in side:
                me = ids[p.player_id]
                won, played = singles[p.player_id]
                if not played:
                    continue
                expected = sum(
                    1 / (1 + 10 ** ((rating[ids[o.player_id]] - rating[me])
                                    / elo.SCALE))
                    for o in others
                )
                step = elo.step_for(career.get(me, 0))
                if season.get(me, 0) < settle_len:
                    step = max(step, settle_floor)
                moves[me] = step * (won / played - expected / len(others))
        for me, delta in moves.items():
            rating[me] += delta
            season[me] = season.get(me, 0) + 1
            career[me] = career.get(me, 0) + 1

    return errors


def _brier(errors):
    return sum(errors) / len(errors)


def _paired(variant, baseline, label):
    """Is the gap between two variants bigger than the sample it came from?"""
    diffs = [v - b for v, b in zip(variant, baseline)]
    n = len(diffs)
    mean = sum(diffs) / n
    rng = random.Random(0)
    boots = sorted(sum(rng.choice(diffs) for _ in range(n)) / n
                   for _ in range(BOOTSTRAPS))
    lo, hi = boots[BOOTSTRAPS // 40], boots[BOOTSTRAPS - BOOTSTRAPS // 40 - 1]
    worse = sum(1 for b in boots if b > 0) / BOOTSTRAPS * 100
    print(f"{label} against no bump:")
    print(f"  Brier penalty  {mean:+.5f}   95% interval {lo:+.5f} to {hi:+.5f}")
    print(f"  worse in {worse:.0f}% of {BOOTSTRAPS} paired resamples\n")


def main() -> None:
    past, now = _load()
    if not now:
        print(f"No {CURRENT} matches cached — nothing to walk through.")
        return

    print(f"Predicting each {CURRENT} match from everything before it.\n")
    print(f"{'start-of-season floor':>22} {'for N matches':>14} "
          f"{'scale':>6} {'Brier':>8}")
    variants = ((0, 0), (40, 6), (60, 6), (80, 6), (120, 6), (160, 6),
                (60, 3), (60, 10))
    for floor, length in variants:
        best = min(range(160, 601, 20),
                   key=lambda sc: _brier(walk(past, now, floor, length, float(sc))))
        brier = _brier(walk(past, now, floor, length, float(best)))
        label = "none" if length == 0 else str(floor)
        shown = "-" if length == 0 else str(length)
        print(f"{label:>22} {shown:>14} {best:>6} {brier:>8.4f}")

    baseline = walk(past, now)
    print(f"\n{len(baseline)} pairings, the same matches in the same order "
          f"for every variant.\n")
    _paired(walk(past, now, 40, 6), baseline, "A floor of 40 for 6 matches")
    _paired(walk(past, now, 160, 6), baseline, "A full restart at 160")


if __name__ == "__main__":
    main()
