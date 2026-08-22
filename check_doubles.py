"""Verify that the 9 singles + 1 doubles match format holds in the data.

The doubles itself is not predicted anywhere — the scraped pages do not say
which two players paired up. What this checks is the arithmetic that lets a
target in match points be stated in singles: if a match is 9 singles plus 1
doubles, then the doubles point is whatever a team's total has over its
singles wins, and the two sides must split it 0/1.

If this reports anomalies, the format is not what the app assumes and the
conversion between singles and match points is wrong. Run it after a scrape.
"""

from cache import load_matches
from webapp.api import _doubles_report


def main() -> None:
    matches = load_matches()
    if not matches:
        print("No cached matches — run `main.py --refresh` first.")
        return

    report = _doubles_report(matches)

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

    print()
    if report["format_holds"]:
        print("The 9 singles + 1 doubles format holds — the singles/points")
        print("conversion in the web app is sound.")
    else:
        print("The format does NOT hold across this data.")
        print("The web app's conversion between singles and match points may be wrong.")


if __name__ == "__main__":
    main()
