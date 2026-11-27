"""Walk both seasons forward, nudging each player toward what their record implies.

walkforward.py walks the current season only, because a start-of-season rule
cannot be seen any other way. The question here is different and needs both
seasons: the engine moves a player only a fraction of the way toward the
rating their results imply, and a mid-season split suggested a quarter of the
rest was signal worth taking. One split of one season is thin, so this walks
every match of both seasons in date order.

At each match a player is predicted on

    model + blend * (implied - model)

where `implied` is solved from every singles result they have had *so far* in
the walk, against the rating each opponent held when they met. Nothing from
the future enters either term. The model rating itself is updated by the
engine's own rule, unchanged, so `blend` alters what is predicted and never
what is learnt -- which is the whole point: it asks whether the information is
already in the record before asking anyone to change step_for().

Scored by Brier over every player-opponent pairing, with a paired bootstrap
over the same pairings, as everywhere else in this project.

    uv run python walkforward_implied.py
"""
import random
import statistics as st
from collections import defaultdict
from datetime import date as _d

import elo
from cache import load_matches
from models import real_singles
from player_identity import identity

SEASONS = ["2025-26", "2026-27"]
MIN_SINGLES = 6      # below this a record says too little to lean on
BOOTSTRAPS = 4000
BISECT = 40


def _start_of(season, matches, carried):
    """Identity-keyed starting ratings, the engine's seeding re-keyed by name.

    _seed_ratings works in player ids because the league reissues them every
    season; the walk works in identities for the same reason walkforward.py
    does. Where two ids fold to one identity the first seed wins, which only
    happens for a player entered twice.
    """
    seeded = elo._seed_ratings(matches, season, None)
    out = {}
    for pid, pr in seeded.items():
        key = identity(pr.name)
        if key not in out:
            out[key] = pr.rating
    out.update(carried)          # a carried rating always beats a fresh seed
    return out


def _implied(opps, won, played):
    """The rating that would have predicted this record, read conservatively.

    Half a win and half a loss are added so that a perfect record stays
    finite and a short one stays humble.
    """
    target = (won + 0.5) / (played + 1) * len(opps)
    lo, hi = -2000.0, 4000.0
    for _ in range(BISECT):
        mid = (lo + hi) / 2
        got = sum(1 / (1 + 10 ** ((o - mid) / elo.PREDICTION_SCALE)) for o in opps)
        if got < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def walk(blend):
    """Every squared error, in walk order, for one blend setting."""
    matches = load_matches() or []
    rating, career = {}, {}
    record = defaultdict(lambda: {"won": 0, "played": 0, "opps": []})
    cache = {}                   # identity -> implied, recomputed on change
    errors = []

    for season in SEASONS:
        now = sorted((m for m in matches if m.season == season),
                     key=lambda m: m.date or _d.min)
        rating = _start_of(season, now, rating)

        for m in now:
            home, away = m.home.players, m.away.players
            ids = {p.player_id: identity(p.name) for p in home + away}
            if not all(v in rating for v in ids.values()):
                continue
            singles = real_singles(m)

            def predictive(key):
                if blend <= 0:
                    return rating[key]
                r = record[key]
                if r["played"] < MIN_SINGLES or not r["opps"]:
                    return rating[key]
                if key not in cache:
                    cache[key] = _implied(r["opps"], r["won"], r["played"])
                return rating[key] + blend * (cache[key] - rating[key])

            # Predict, from records and ratings that have not seen this match.
            for side, others in ((home, away), (away, home)):
                for p in side:
                    me = ids[p.player_id]
                    won, played = singles[p.player_id]
                    if not played:
                        continue
                    share = won / len(others)
                    mine = predictive(me)
                    for o in others:
                        gap = mine - predictive(ids[o.player_id])
                        errors.append(
                            (1 / (1 + 10 ** (-gap / elo.PREDICTION_SCALE)) - share) ** 2)

            # Then update the model, both sides from the same pre-match ratings.
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
                        for o in others)
                    moves[me] = elo.step_for(career.get(me, 0)) * (
                        won / played - expected / len(others))
            for me, delta in moves.items():
                rating[me] += delta
                career[me] = career.get(me, 0) + 1

            # And grow the records the blend reads, against the ratings the
            # opponents held at the time rather than any later figure.
            for side, others in ((home, away), (away, home)):
                for p in side:
                    me = ids[p.player_id]
                    won, played = singles[p.player_id]
                    if not played:
                        continue
                    r = record[me]
                    r["won"] += won
                    r["played"] += played
                    r["opps"].extend(rating[ids[o.player_id]] for o in others)
                    cache.pop(me, None)

    return errors


def main():
    random.seed(20261127)
    base = walk(0.0)
    print(f"both seasons, {len(base)} pairings predicted out of sample")
    print(f"\n  {'blend':>7} {'Brier':>8} {'vs engine':>11}   95% paired band")
    print(f"  {'engine':>7} {st.mean(base):8.4f}")
    for blend in (0.10, 0.15, 0.25, 0.35, 0.50, 0.75, 1.00):
        e = walk(blend)
        if len(e) != len(base):
            print(f"  {blend:7.2f}  pairing counts differ; not comparable")
            continue
        paired = [a - b for a, b in zip(e, base)]
        boot = sorted(st.mean(random.choices(paired, k=len(paired)))
                      for _ in range(BOOTSTRAPS))
        lo, hi = boot[int(0.025 * BOOTSTRAPS)], boot[int(0.975 * BOOTSTRAPS)]
        verdict = ("better" if hi < 0 else "worse" if lo > 0
                   else "crosses zero")
        print(f"  {blend:7.2f} {st.mean(e):8.4f} {st.mean(paired):+11.5f}   "
              f"{lo:+.5f} to {hi:+.5f}  {verdict}")


if __name__ == "__main__":
    main()
