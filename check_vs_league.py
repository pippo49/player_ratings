"""Does our engine predict better than the league's published ranking?

This is the question that decides the weekly routine. If the league's own
ranking is as good, the week costs three saved pages; if ours is better, it
costs a match card per fixture and the effort buys something.

`compare_rankings.py` answers it from saved ranking pages. This answers it
from what is already cached, so it can be re-run any week without saving
anything: the league's numbers are already in the published payload, and
ours are recomputed here.

Fair means neither side sees what it is predicting. Ours is rated on the
completed seasons alone and then asked about the current one. Theirs cannot
be rewound -- the payload holds their current numbers, which already include
the matches being scored -- so the comparison is tilted in their favour and
any win for ours is a floor, not a ceiling.

Each side's scale is fitted on the completed seasons only, so neither is
tuned to the matches it is scored on. Brier throughout; see "How to judge a
change to the ratings" in HANDOFF.md for why not mean absolute error.

    python check_vs_league.py
"""
import json
import random
from pathlib import Path

import elo
from cache import load_matches
from models import real_singles

CURRENT = "2026-27"
PAYLOAD = Path(__file__).parent / "webapp" / "static" / "ratings.json"
BOOTSTRAPS = 4000


def _brier(ps: list[tuple[float, float]], scale: float) -> float:
    return sum((1 / (1 + 10 ** (-g / scale)) - s) ** 2 for g, s in ps) / len(ps)


def _pairs(ms, ratings, eligible):
    """Every singles pairing as (rating gap, share of the three won)."""
    out = []
    for m in ms:
        singles = real_singles(m)
        for side, others in ((m.home, m.away), (m.away, m.home)):
            for p in side.players:
                won, played = singles[p.player_id]
                if not played or p.name not in eligible:
                    continue
                for o in others.players:
                    if o.name in eligible:
                        out.append((ratings[p.name] - ratings[o.name],
                                    won / len(others.players)))
    return out


def main() -> None:
    payload = json.loads(PAYLOAD.read_text())
    theirs = {p["name"]: p["rating_tt365"] for p in payload["players"]
              if p.get("ranked_tt365") and p.get("rating_tt365") is not None}
    if not theirs:
        print("The payload carries no league ratings — import a ranking page "
              "first, then re-run.")
        return

    matches = load_matches() or []
    past = [m for m in matches if m.season != CURRENT]
    now = [m for m in matches if m.season == CURRENT]
    if not now:
        print(f"No {CURRENT} matches cached — nothing to score against.")
        return

    ours = {pr.name: pr.rating for pr in elo.calculate_ratings(past).values()}
    # Only players both systems rate, or the two are answering different
    # questions on different populations.
    eligible = set(ours) & set(theirs)
    print(f"{len(eligible)} players carry both a rating of ours and one of "
          f"theirs.\n")

    scored = {}
    for label, ratings, lo, hi in (("ours", ours, 100, 900),
                                   ("the league's", theirs, 300, 3000)):
        scale = min(range(lo, hi, 5),
                    key=lambda s: _brier(_pairs(past, ratings, eligible),
                                         float(s)))
        test = _pairs(now, ratings, eligible)
        scored[label] = (_brier(test, float(scale)), scale, test)
        print(f"{label:>13}: scale {scale} fitted on the completed seasons, "
              f"Brier {scored[label][0]:.4f} on {len(test)} pairings")

    flat = scored["ours"][2]
    print(f"{'no ratings':>13}: Brier "
          f"{sum((0.5 - s) ** 2 for _, s in flat) / len(flat):.4f} "
          f"(guessing 50-50)")

    # Paired, so the verdict is not an artefact of which matches landed in
    # the sample: the same pairings are scored both ways.
    a, sa, pa = scored["ours"]
    b, sb, pb = scored["the league's"]
    diffs = [((1 / (1 + 10 ** (-g2 / sb)) - s2) ** 2)
             - ((1 / (1 + 10 ** (-g1 / sa)) - s1) ** 2)
             for (g1, s1), (g2, s2) in zip(pa, pb)]
    n = len(diffs)
    rng = random.Random(0)
    boots = sorted(sum(rng.choice(diffs) for _ in range(n)) / n
                   for _ in range(BOOTSTRAPS))
    mean = sum(diffs) / n
    ahead = sum(1 for x in boots if x > 0) / BOOTSTRAPS * 100
    winner = "Ours" if mean > 0 else "Theirs"
    print(f"\nPaired over the same {n} pairings:")
    print(f"  {winner.lower()} better by {abs(mean):.4f} Brier"
          f"   95% interval {boots[BOOTSTRAPS // 40]:+.4f} to "
          f"{boots[BOOTSTRAPS - BOOTSTRAPS // 40 - 1]:+.4f}")
    print(f"  ours ahead in {ahead:.0f}% of {BOOTSTRAPS} resamples")
    print(f"\n{winner} predicts better. Theirs has already seen these "
          f"matches and ours has not,\nso the gap in our favour is a floor.")


if __name__ == "__main__":
    main()
