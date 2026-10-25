"""What rating gap actually means a given chance of winning.

The engine computes expected scores with Elo's constant of 400. Whether
that is right for this league is a question with an answer: rate on last
season, then see which constant best predicts this one.

It does not come out at 400. A constant that is too high damps every
expected score towards a half, which damps every rating update, which is
why a player can lose fifteen straight and move barely a hundred points —
and it flattens every team projection towards five points a match.

    uv run python fit_scale.py
"""

import sys
from cache import load_matches
from elo import calculate_ratings
from models import real_singles
from player_identity import identity

matches = load_matches() or []
past = [m for m in matches if m.season != "2026-27"]
now = [m for m in matches if m.season == "2026-27"]
before = calculate_ratings(past)

cases = []
for match in now:
    singles = real_singles(match)
    for side, other in ((match.home, match.away), (match.away, match.home)):
        for p in side.players:
            me = identity(p.name)
            opp = [identity(o.name) for o in other.players]
            if me not in before or not all(o in before for o in opp):
                continue
            won, played = singles[p.player_id]
            if played:
                cases.append((before[me].rating, [before[o].rating for o in opp], won))

def err(scale):
    t = 0.0
    for mine, gaps, won in cases:
        e = sum(1 / (1 + 10 ** ((g - mine) / scale)) for g in gaps)
        t += abs(e - won)
    return t / len(cases)

print(f"\n{len(cases)} player-matches, ratings from last season only (out of sample)")
print(f"{'scale':>7} {'error':>7}")
for s in (60, 90, 150, 200, 260, 300, 400, 600):
    print(f"{s:>7} {err(s):>7.3f}{'   <- what the engine uses' if s == 400 else ''}")
best = min(range(20, 1001, 5), key=err)
print(f"\nbest fit: {best}  (error {err(best):.3f})")
