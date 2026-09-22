"""Report league page structure, for writing parsers against.

The site is only reachable with open internet, and artifact storage is not
reachable from the development sandbox, so this prints a bounded summary to
stdout to be read back from the job log.

    .venv/bin/python3 fetch_pages.py 2026-27
"""

import json
import re
import sys
import time
from collections import Counter

import requests
from bs4 import BeautifulSoup

from scraper import BASE_URL, LEAGUE, REQUEST_DELAY, _season_slug

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ratings-bot/1.0)"}
OLD_BASE = "https://old.tabletennis365.com"

LEGACY = {"home": "home", "away": "away", "playerName": "playerName", "score": "score"}


def get(url: str) -> str | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
    except Exception as exc:
        print(f"    FAILED {type(exc).__name__}: {exc}")
        return None
    finally:
        time.sleep(REQUEST_DELAY)
    print(f"    HTTP {r.status_code}, {len(r.text)} bytes")
    return r.text if r.status_code == 200 else None


def legacy_counts(soup) -> str:
    return ", ".join(f"{k}={len(soup.find_all(class_=v))}" for k, v in LEGACY.items())


def tt_classes(soup, limit=18) -> None:
    c = Counter()
    for tag in soup.find_all(class_=True):
        for cls in tag.get("class", []):
            if cls.startswith("tt-") and "langswitch" not in cls and "footer" not in cls:
                c[f"{tag.name}.{cls}"] += 1
    for name, n in c.most_common(limit):
        print(f"      {n:>4}  {name}")


def main() -> None:
    season = sys.argv[1] if len(sys.argv) > 1 else "2026-27"
    slug = _season_slug(season)

    # 1. Does the old site still serve the layout the parser was written for?
    print("=== OLD SITE — does the legacy layout survive? ===")
    for section in ("Fixtures", "Results"):
        url = f"{OLD_BASE}/{LEAGUE}/{section}/{slug}/Division_Four"
        print(f"  {url}")
        html = get(url)
        if html:
            soup = BeautifulSoup(html, "html.parser")
            print(f"    legacy: {legacy_counts(soup)}")
            print(f"    MatchCard links: {len(soup.find_all('a', href=re.compile('/MatchCard/')))}")

    # 2. New tables page — the team list and their links.
    print("\n=== NEW SITE — Tables/Division_Four ===")
    html = get(f"{BASE_URL}/{LEAGUE}/Tables/{slug}/Division_Four")
    team_url = None
    if html:
        soup = BeautifulSoup(html, "html.parser")
        links = soup.find_all("a", class_="tt-team-link")
        print(f"    tt-team-link count: {len(links)}")
        for a in links[:14]:
            print(f"      {a.get_text(strip=True)!r} -> {a.get('href')}")
        if links:
            href = links[0]["href"]
            team_url = href if href.startswith("http") else BASE_URL + href

    # 3. New fixtures page — is the content server-rendered at all?
    print("\n=== NEW SITE — Fixtures/Division_Four ===")
    html = get(f"{BASE_URL}/{LEAGUE}/Fixtures/{slug}/Division_Four")
    if html:
        soup = BeautifulSoup(html, "html.parser")
        print(f"    legacy: {legacy_counts(soup)}")
        print("    tt- classes:")
        tt_classes(soup)
        print(f"    tables: {len(soup.find_all('table'))}, rows: {len(soup.find_all('tr'))}")
        # Server-rendered, or hydrated from embedded JSON?
        for s in soup.find_all("script"):
            txt = s.string or ""
            if len(txt) > 400 and ("fixture" in txt.lower() or "match" in txt.lower()):
                print(f"    script with match data, {len(txt)} chars, starts: {txt.strip()[:200]}")
                break
        else:
            print("    no embedded match JSON found in <script>")

    # 4. A team page — the squad list.
    if team_url:
        print(f"\n=== NEW SITE — team page ===\n    {team_url}")
        html = get(team_url)
        if html:
            soup = BeautifulSoup(html, "html.parser")
            print("    tt- classes:")
            tt_classes(soup)
            players = soup.find_all("a", href=re.compile(r"/Player"))
            print(f"    player links: {len(players)}")
            for a in players[:12]:
                print(f"      {a.get_text(strip=True)!r} -> {a.get('href')}")


if __name__ == "__main__":
    main()
