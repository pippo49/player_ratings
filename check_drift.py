"""Does playing above your own division pay you rating points?

The mechanics say no: a bigger payout for beating a stronger player is
exactly offset by a smaller penalty for losing to them, so if the win
probability is right the expected change is zero whoever you face. That
cancellation is the whole design.

It only holds if the probability is right. This measures it directly on the
matches we have: for every singles pairing, is the player appearing above,
at, or below the division they registered in, and does the model's expected
score match what actually happened?
"""


from collections import defaultdict
import elo
from cache import load_matches
from models import real_singles
from player_identity import identity, normalise

matches = load_matches() or []
ratings = elo.calculate_ratings(matches)

rows = defaultdict(lambda: [0.0, 0.0, 0])   # actual, expected, pairings
drift = defaultdict(lambda: [0.0, 0])       # summed rating change, players

for season in ("2025-26", "2026-27"):
    reg = {normalise(k): v for k, v in
           elo.load_registered_divisions(season).items()}
    for m in (x for x in matches if x.season == season):
        singles = real_singles(m)
        for side, others in ((m.home, m.away), (m.away, m.home)):
            for p in side.players:
                me = identity(p.name)
                if me not in ratings:
                    continue
                won, played = singles[p.player_id]
                if not played:
                    continue
                own = reg.get(normalise(p.name))
                if own is None:
                    continue
                # Division numbers run high=weak, so a smaller number for
                # the match than for your registration means playing up.
                step = m.division - own
                where = ("playing up" if step < 0
                         else "own division" if step == 0 else "playing down")
                for o in others.players:
                    oid = identity(o.name)
                    if oid not in ratings:
                        continue
                    exp = elo.win_probability(ratings[me].rating,
                                              ratings[oid].rating)
                    r = rows[where]
                    r[0] += won / len(others.players)
                    r[1] += exp
                    r[2] += 1

print("Model's expected wins against what actually happened\n")
print(f"{'':>14} {'pairings':>9} {'actual':>8} {'predicted':>10} {'gap':>8}")
for where in ("playing up", "own division", "playing down"):
    a, e, n = rows[where]
    if not n:
        continue
    print(f"{where:>14} {n:>9} {a/n:>8.3f} {e/n:>10.3f} {a/n - e/n:>+8.3f}")

a, e, n = rows["playing up"]
if n:
    print(f"\nPlaying up, each singles match pays on average "
          f"{elo.K_FLOOR * (a/n - e/n):+.2f} rating points at the settled "
          f"step of {elo.K_FLOOR:.0f},")
    print(f"and {160 * (a/n - e/n):+.2f} for a brand-new player at a step of 160.")
