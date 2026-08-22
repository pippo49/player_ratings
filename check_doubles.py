"""Verify that the doubles point can be recovered from the scraped data.

A team match is 9 singles plus 1 doubles, so 10 points are on offer. The
scraped pages give each player's singles wins and the team's total, which
means the doubles point is whatever is left over:

    doubles_point = total_score - sum(singles won by that team's players)

That should always be 0 or 1, and the two sides should always split it. If
this script reports anomalies, the assumption does not hold and the web
app's doubles model should not be trusted — run it after a scrape and
before relying on the points projection.
"""

from cache import load_matches
from elo import calculate_ratings
from webapp.api import _doubles_report


def main() -> None:
    matches = load_matches()
    if not matches:
        print("No cached matches — run `main.py --refresh` first.")
        return

    report = _doubles_report(matches, calculate_ratings(matches))

    print(f"Matches examined            : {report['matches']}")
    print(f"Doubles point recovered     : {report['recovered']}")
    print(f"Anomalies (not 0/1 split)   : {report['anomalies']}")

    if report["anomalies"]:
        print("\n  Anomalous matches — the 9 singles + 1 doubles assumption fails here:")
        for m in matches:
            home = m.home.total_score - sum(p.games_won for p in m.home.players)
            away = m.away.total_score - sum(p.games_won for p in m.away.players)
            if {home, away} != {0, 1}:
                print(
                    f"    Div {m.division} {m.date} "
                    f"{m.home.name} {m.home.total_score} v {m.away.total_score} {m.away.name} "
                    f"(leftover {home}/{away})"
                )

    if report["home_win_rate"] is not None:
        print(f"\nHome side wins the doubles  : {report['home_win_rate'] * 100:.1f}%")
    if report["model_accuracy"] is not None:
        print(f"Model accuracy              : {report['model_accuracy'] * 100:.1f}%")
        print(f"Model Brier score           : {report['model_brier']:.4f}  (0.25 = coin flip)")

    print()
    if report["trustworthy"]:
        print("The doubles point is recoverable — the points projection is on solid ground.")
    else:
        print("The doubles point could NOT be reliably recovered.")
        print("Treat the 10th point in the web app as a guess until this is resolved.")


if __name__ == "__main__":
    main()
