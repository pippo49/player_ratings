"""A total fetch failure must be loud, a missing season quiet.

Six days of scheduled runs reported success while every page returned
403, because "fetched nothing" and "nothing new" ended in the same
place. These four cases are the difference.

    python test_scrape_failure.py
"""

import sys
import requests
import scraper
from scraper import SeasonUnreachable

def http_error(status):
    r = requests.Response()
    r.status_code = status
    return requests.HTTPError(f"{status} Client Error", response=r)

SLUGS = [(f"Division_{n}", i) for i, n in enumerate(["One", "Two", "Three"], 1)]
scraper.division_slugs = lambda season: SLUGS
scraper.time.sleep = lambda *_: None

def run(behaviour, label):
    scraper.scrape_division_page = behaviour
    try:
        out = scraper.scrape_season("2026-27", verbose=False)
        print(f"  {label:38s} -> returned {len(out)} match(es)")
        return None
    except SeasonUnreachable as e:
        print(f"  {label:38s} -> RAISED ({len(e.failures)} divisions)")
        return e

print("scrape_season:")
run(lambda *a, **k: (_ for _ in ()).throw(http_error(403)), "every division 403 (the real bug)")
run(lambda *a, **k: (_ for _ in ()).throw(http_error(404)), "every division 404 (not published)")
calls = {"n": 0}
def one_bad(*a, **k):
    calls["n"] += 1
    if calls["n"] == 1:
        raise http_error(403)
    return ["match"]
run(one_bad, "one 403, the rest fine")

print("\nscrape_all_divisions (2 seasons):")
scraper.SEASONS = ["2025-26", "2026-27"]
scraper.scrape_division_page = lambda *a, **k: (_ for _ in ()).throw(http_error(403))
try:
    scraper.scrape_all_divisions(verbose=False)
    print("  both seasons refused                   -> returned (WRONG)")
except SeasonUnreachable:
    print("  both seasons refused                   -> RAISED")

state = {"season": None}
def per_season(div, num, season, known=None):
    if season == "2025-26":
        raise http_error(403)
    return ["match"]
scraper.scrape_division_page = per_season
out = scraper.scrape_all_divisions(verbose=False)
print(f"  old season dark, current season fine   -> returned {len(out)} match(es)")
