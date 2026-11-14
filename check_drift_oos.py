"""The playing-up question, out of sample.

check_drift.py rates on every match and then splits those same matches by
bucket. Convergence drives expected towards actual by construction, so a
bucket can be pushed off zero by the fitting rather than by anything real.

Rating on 2025-26 alone and asking only about 2026-27 removes that. The
sample gets smaller, which is the honest cost.
"""
import random
from collections import defaultdict
import elo
from cache import load_matches
from models import real_singles
from player_identity import identity, normalise

matches = load_matches() or []
trained = elo.calculate_ratings([m for m in matches if m.season != "2026-27"])
r = {pr.name: pr.rating for pr in trained.values()}
reg = {normalise(k): v for k, v in elo.load_registered_divisions("2026-27").items()}

buckets = {"playing up": defaultdict(lambda: [0.0, 0.0, 0]),
           "own division": defaultdict(lambda: [0.0, 0.0, 0])}
for m in (x for x in matches if x.season == "2026-27"):
    singles = real_singles(m)
    for side, others in ((m.home, m.away), (m.away, m.home)):
        for p in side.players:
            own = reg.get(normalise(p.name))
            if p.name not in r or own is None:
                continue
            won, played = singles[p.player_id]
            if not played:
                continue
            where = ("playing up" if m.division < own
                     else "own division" if m.division == own else None)
            if where is None:
                continue
            for o in others.players:
                if o.name not in r:
                    continue
                row = buckets[where][(m.match_id, p.name)]
                row[0] += won / len(others.players)
                row[1] += 1/(1+10**((r[o.name]-r[p.name])/elo.PREDICTION_SCALE))
                row[2] += 1

for where, nights in buckets.items():
    rows = list(nights.values())
    if not rows:
        continue
    tot = sum(x[2] for x in rows)
    gap = sum(x[0] for x in rows)/tot - sum(x[1] for x in rows)/tot
    rng = random.Random(0)
    boots = []
    for _ in range(4000):
        pick = [rng.choice(rows) for _ in range(len(rows))]
        t = sum(x[2] for x in pick)
        boots.append(sum(x[0] for x in pick)/t - sum(x[1] for x in pick)/t)
    boots.sort()
    lo, hi = boots[100], boots[3899]
    verdict = "clear of zero" if (lo < 0) == (hi < 0) else "CROSSES ZERO"
    print(f"{where:14s} {len(rows):>4} player-nights, {tot:>5} pairings  "
          f"gap {gap:+.3f}   95% {lo:+.3f} to {hi:+.3f}   {verdict}")
