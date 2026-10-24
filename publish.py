"""Scrape from this machine and publish the result to the phone app.

One command: fetch what is new, rebuild the snapshot, commit it and push.
GitHub Pages redeploys on the push, so the app has the new results about a
minute later.

    uv run python publish.py            # fetch results and publish
    uv run python publish.py --squads   # also refresh squads (slower)
    uv run python publish.py --dry-run  # fetch and report, commit nothing

Why from here rather than from GitHub: since 18 October 2026 Cloudflare has
challenged the scheduled runs, which come from datacenter IPs. A home
connection is a different profile. If this is challenged here too, it will
say so plainly rather than reporting success and publishing nothing.
"""

import argparse
import subprocess
import sys
from datetime import date

from cache import CACHE_FILE, load_matches, merge_matches, save_matches
from models import Match
from scraper import CURRENT_SEASON, SeasonUnreachable, scrape_all_divisions
from webapp.export import export

PUBLISHED = ["data", "webapp/static/ratings.json"]


def git(*args: str, check: bool = True) -> str:
    """Run a git command and return its output."""
    done = subprocess.run(
        ["git", *args], capture_output=True, text=True, check=False
    )
    if check and done.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed:\n{done.stderr.strip()}")
    return done.stdout.strip()


def describe(matches: list[Match]) -> list[str]:
    """New results, newest first, as one line each."""
    rows = sorted(matches, key=lambda m: (m.date or date.min), reverse=True)
    return [
        f"  {m.date}  D{m.division}  {m.home.name} "
        f"{m.home.total_score}-{m.away.total_score} {m.away.name}"
        for m in rows
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--squads", action="store_true",
                    help="also refresh team squads — slower, every team page")
    ap.add_argument("--dry-run", action="store_true",
                    help="fetch and report, but do not commit or push")
    args = ap.parse_args()

    cached = load_matches() or []
    known = {(m.season, m.match_id) for m in cached if m.match_id}

    print("Fetching results from the league…\n")
    try:
        scraped = scrape_all_divisions(verbose=True, known=known)
    except SeasonUnreachable as e:
        # The whole point of running from here. Say which wall we hit.
        print(f"\nThe league site would not answer.\n\n{e}\n")
        if "403" in str(e):
            print("A 403 from here as well means the challenge is not about\n"
                  "where the request comes from. Nothing was changed.")
        return 1

    matches, added = merge_matches(cached, scraped)
    if not added:
        print("\nNothing new — the app is already up to date.")
        return 0

    new_ones = matches[len(cached):]
    print(f"\n{added} new result(s):")
    print("\n".join(describe(new_ones)))

    save_matches(matches)
    if args.squads:
        # fetch_squads reads its season from argv, so hand it one.
        import fetch_squads
        print("\nRefreshing squads…")
        argv, sys.argv = sys.argv, ["fetch_squads.py", CURRENT_SEASON]
        try:
            fetch_squads.main()
        finally:
            sys.argv = argv
    export()

    if args.dry_run:
        print("\n--dry-run: nothing committed. "
              f"{CACHE_FILE} and the snapshot were written.")
        return 0

    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if branch != "master":
        print(f"\nOn branch {branch}, not master — publishing from here would "
              "not deploy.\nSwitch to master and run again.")
        return 1

    print("\nPublishing…")
    # Someone else's run may have committed in the meantime; rebase rather
    # than merge so the history stays a straight line of scrapes.
    git("pull", "--rebase", "origin", "master")
    git("add", *PUBLISHED)
    if not git("status", "--porcelain", "--", *PUBLISHED):
        print("Nothing to commit after all — already published.")
        return 0
    git("commit", "-m", f"Add {added} new result(s) from a local scrape")
    git("push", "origin", "master")

    print(f"\nDone. {added} result(s) published — the app updates in about a "
          "minute.\nReopen it and it will pick them up on its own.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
