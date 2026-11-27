"""Would loosening the step itself do the job, and better?

The blend test asks whether a player's record holds information the engine
has not taken. It does, a little. But a blend is a patch applied at
prediction time: the ratings stay where they were, so everything else that
reads a rating still reads the old one.

The change you would actually ship is to the step schedule. This walks both
seasons with the engine untouched except for K_FLOOR and K_HALF_LIFE, so a
different step changes the ratings themselves, and scores the same way.

    uv run python walkforward_step.py
"""
import random
import statistics as st
from datetime import date as _d

import elo
from cache import load_matches
from models import real_singles
from player_identity import identity

SEASONS = ["2025-26", "2026-27"]
BOOTSTRAPS = 4000


def _start_of(season, matches, carried):
    seeded = elo._seed_ratings(matches, season, None)
    out = {}
    for pid, pr in seeded.items():
        key = identity(pr.name)
        if key not in out:
            out[key] = pr.rating
    out.update(carried)
    return out


def walk(floor, half_life, start):
    """Brier errors in walk order, with this step schedule."""
    step_for = lambda c: max(floor, start / (1 + c / half_life))
    matches = load_matches() or []
    rating, career, errors = {}, {}, []

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
            for side, others in ((home, away), (away, home)):
                for p in side:
                    me = ids[p.player_id]
                    won, played = singles[p.player_id]
                    if not played:
                        continue
                    share = won / len(others)
                    for o in others:
                        gap = rating[me] - rating[ids[o.player_id]]
                        errors.append(
                            (1 / (1 + 10 ** (-gap / elo.PREDICTION_SCALE)) - share) ** 2)
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
                    moves[me] = step_for(career.get(me, 0)) * (
                        won / played - expected / len(others))
            for me, delta in moves.items():
                rating[me] += delta
                career[me] = career.get(me, 0) + 1
    return errors


def main():
    random.seed(20261127)
    F, H, S = elo.K_FLOOR, elo.K_HALF_LIFE, elo.K_START
    base = walk(F, H, S)
    print(f"both seasons, {len(base)} pairings\n")
    print(f"  {'floor':>6} {'halflife':>9} {'start':>6} {'Brier':>8} "
          f"{'vs engine':>11}   95% paired band")
    print(f"  {F:6.0f} {H:9.0f} {S:6.0f} {st.mean(base):8.4f}"
          f"   {'(the engine as it stands)':>28}")
    trials = [
        (25.0, H, S), (30.0, H, S), (40.0, H, S), (60.0, H, S),
        (F, 4.0, S), (F, 6.0, S), (F, 9.0, S),
        (30.0, 6.0, S), (40.0, 6.0, S), (30.0, 9.0, S),
        (F, H, 200.0), (F, H, 120.0),
    ]
    for floor, hl, start in trials:
        e = walk(floor, hl, start)
        if len(e) != len(base):
            print(f"  {floor:6.0f} {hl:9.0f} {start:6.0f}  counts differ")
            continue
        paired = [a - b for a, b in zip(e, base)]
        boot = sorted(st.mean(random.choices(paired, k=len(paired)))
                      for _ in range(BOOTSTRAPS))
        lo, hi = boot[int(0.025 * BOOTSTRAPS)], boot[int(0.975 * BOOTSTRAPS)]
        verdict = "better" if hi < 0 else "worse" if lo > 0 else "crosses zero"
        print(f"  {floor:6.0f} {hl:9.0f} {start:6.0f} {st.mean(e):8.4f} "
              f"{st.mean(paired):+11.5f}   {lo:+.5f} to {hi:+.5f}  {verdict}")


if __name__ == "__main__":
    main()
