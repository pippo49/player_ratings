"""Does the division ladder match what call-ups actually do?

Ratings are seeded a hundred points apart per division, and nothing ever
tests that gap: players meet their own division almost exclusively. The
exception is a call-up, who plays in the division they were borrowed
into — the only cross-division evidence there is.

    uv run python check_ladder.py

A positive gap means call-ups do better than the ladder expects, so the
ladder is too steep for the prediction scale in use.
"""

import sys
from collections import defaultdict
import elo
from cache import load_matches
from models import real_singles
from player_identity import identity

matches = load_matches() or []
rated = elo.calculate_ratings(matches)
S = elo.PREDICTION_SCALE

# Where a player turned out in a division other than the one their rating
# was seeded from. That is the only cross-division evidence there is.
reg = {}
for season in ("2025-26", "2026-27"):
    for pid, div in elo.load_registered_divisions(season).items():
        reg[(season, pid)] = div

rows = []
for m in matches:
    singles = real_singles(m)
    for side, other in ((m.home, m.away), (m.away, m.home)):
        for p in side.players:
            pid = identity(p.name)
            home_div = reg.get((m.season, pid))
            if home_div is None or home_div == m.division or pid not in rated:
                continue
            opp = [identity(o.name) for o in other.players]
            if not all(o in rated for o in opp):
                continue
            won, played = singles[p.player_id]
            if not played:
                continue
            pred = sum(1 / (1 + 10 ** ((rated[o].rating - rated[pid].rating) / S))
                       for o in opp)
            rows.append((home_div - m.division, won, played, pred, p.name))

print(f"{len(rows)} appearances in a division other than the registered one\n")
print(f"{'steps up':>9} {'cases':>6} {'actual':>8} {'predicted':>10} {'gap':>7}")
by_step = defaultdict(list)
for step, won, played, pred, _ in rows:
    by_step[step].append((won, pred))
for step in sorted(by_step, reverse=True):
    group = by_step[step]
    a = sum(w for w, _ in group) / len(group)
    e = sum(p for _, p in group) / len(group)
    label = f"+{step}" if step > 0 else str(step)
    print(f"{label:>9} {len(group):>6} {a:>8.2f} {e:>10.2f} {a - e:>+7.2f}")

up = [(w, p) for s, w, _, p, _ in rows if s > 0]
if up:
    a = sum(w for w, _ in up) / len(up)
    e = sum(p for _, p in up) / len(up)
    print(f"\nplaying up, all steps: {len(up)} cases, "
          f"actual {a:.2f} wins of 3, model says {e:.2f}, gap {a - e:+.2f}")
    print("a positive gap means call-ups do better than the ladder expects,")
    print("i.e. the 100-points-per-division ladder is too steep.")
