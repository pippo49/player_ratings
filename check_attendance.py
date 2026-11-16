"""Does last season's attendance help predict who a team will field?

expectedTrio weights each player by how often they have turned out THIS
season. Early on that is a four-match sample, and it can be badly wrong:
Tony Lee played 16 of Irving 4's 20 matches last season but one of Irving
3's first four, so the model cannot select him at all.

The fix to test: treat last season's attendance rate as a prior worth w
matches, so a player with a long record of turning out is not written off
by a couple of early absences.

    rate = (appearances this season + w * last season's rate)
           / (team matches this season + w)

w = 0 is the current method. The test walks forward through 2026-27: at
each match, predict each side's trio from what was known beforehand, and
compare the predicted trio's mean rating with the trio actually fielded.
"""
from collections import defaultdict
from datetime import date as _d

import elo
from cache import load_matches
from player_identity import identity

matches = load_matches() or []
ratings = {identity(p.name): p.rating for p in elo.calculate_ratings(matches).values()}

past = [m for m in matches if m.season != "2026-27"]
now = sorted((m for m in matches if m.season == "2026-27"),
             key=lambda m: m.date or _d.min)

# Last season: how often did each player turn out for the side they played
# most for? Team names change between seasons, so this is per player.
last_apps, team_games = defaultdict(int), defaultdict(int)
player_team = {}
for m in past:
    for side in (m.home, m.away):
        team_games[side.name] += 1
        for p in side.players:
            last_apps[identity(p.name)] += 1
            player_team.setdefault(identity(p.name), side.name)
last_rate = {k: min(1.0, v / max(team_games[player_team[k]], 1))
             for k, v in last_apps.items()}


def trio(squad, apps, played, w):
    """The three this side is expected to field, weighted by turnout rate."""
    ranked = sorted(squad, key=lambda k: -ratings.get(k, 0))
    if len(ranked) <= 3:
        return ranked
    weight = {}
    for k in ranked:
        r = (apps.get(k, 0) + w * last_rate.get(k, 0.5)) / (played + w) if (played + w) else 0
        weight[k] = max(r, 1e-9)
    total = sum(weight.values())
    out = []
    for q in (1/6, 3/6, 5/6):
        target, cum, pick = q * total, 0.0, ranked[-1]
        for k in ranked:
            cum += weight[k]
            if cum >= target:
                pick = k
                break
        out.append(pick)
    return out


def run(w):
    apps = defaultdict(lambda: defaultdict(int))   # team -> player -> count
    played = defaultdict(int)                      # team -> matches so far
    squads = defaultdict(set)
    err, n = 0.0, 0
    for m in now:
        for side in (m.home, m.away):
            keys = [identity(p.name) for p in side.players]
            known = squads[side.name] | set(keys)
            if played[side.name] >= 1 and len(known) > 3:
                pred = trio(sorted(known), apps[side.name], played[side.name], w)
                a = sum(ratings.get(k, 0) for k in pred) / 3
                b = sum(ratings.get(k, 0) for k in keys) / len(keys)
                err += abs(a - b)
                n += 1
        for side in (m.home, m.away):
            played[side.name] += 1
            for p in side.players:
                apps[side.name][identity(p.name)] += 1
                squads[side.name].add(identity(p.name))
    return err / n, n


print("How far the predicted trio's mean rating sits from the one actually")
print("fielded, walking forward through 2026-27.\n")
print(f"{'prior weight w':>15} {'mean error':>12}")
best = None
for w in (0, 1, 2, 3, 4, 6, 8, 12, 20):
    e, n = run(w)
    mark = "   <- current method" if w == 0 else ""
    print(f"{w:>15} {e:>11.1f}{mark}")
    if best is None or e < best[1]:
        best = (w, e)
print(f"\n{n} side-matches judged. Best w = {best[0]} at {best[1]:.1f} points.")


def errors(w):
    """Per-case errors, so two settings can be compared on the same cases."""
    apps = defaultdict(lambda: defaultdict(int))
    played = defaultdict(int)
    squads = defaultdict(set)
    out = []
    for m in now:
        for side in (m.home, m.away):
            keys = [identity(p.name) for p in side.players]
            known = squads[side.name] | set(keys)
            if played[side.name] >= 1 and len(known) > 3:
                pred = trio(sorted(known), apps[side.name], played[side.name], w)
                a = sum(ratings.get(k, 0) for k in pred) / 3
                b = sum(ratings.get(k, 0) for k in keys) / len(keys)
                out.append((played[side.name], abs(a - b)))
        for side in (m.home, m.away):
            played[side.name] += 1
            for p in side.players:
                apps[side.name][identity(p.name)] += 1
                squads[side.name].add(identity(p.name))
    return out


import random
print("\n--- is it real? paired over the same cases ---")
for w in (4, 6, 20):
    a = errors(0)
    b = errors(w)
    diffs = [x[1] - y[1] for x, y in zip(a, b)]      # positive = w is better
    n = len(diffs)
    rng = random.Random(0)
    boots = sorted(sum(rng.choice(diffs) for _ in range(n)) / n for _ in range(4000))
    lo, hi = boots[100], boots[3899]
    print(f"w={w:<3} improves by {sum(diffs)/n:5.1f} points "
          f"(95% {lo:+.1f} to {hi:+.1f}), better in "
          f"{sum(1 for x in boots if x > 0)/40:.0f}% of resamples")

print("\n--- does it still help once a team has a real record? ---")
for w in (4, 6, 20):
    a, b = errors(0), errors(w)
    for lo_n, hi_n, label in ((1, 3, "matches 1-3"), (4, 99, "match 4 onwards")):
        pairs = [(x[1], y[1]) for x, y in zip(a, b) if lo_n <= x[0] <= hi_n]
        if pairs:
            print(f"  w={w:<3} {label:17s} {sum(p for p, _ in pairs)/len(pairs):5.1f} "
                  f"-> {sum(q for _, q in pairs)/len(pairs):5.1f}  ({len(pairs)} cases)")
