"""Report league page structure, for writing parsers against.

Run against a finished season (2025-26) to see played fixtures and match
cards: the 2026/27 season has barely started, but the redesigned site serves
last season's results in the new markup, and those results are already
parsed correctly by the old scraper — so they double as a test oracle.

    .venv/bin/python3 fetch_pages.py 2025-26
"""

import re
import sys
import time
from collections import Counter

import requests
from bs4 import BeautifulSoup

from scraper import BASE_URL, LEAGUE, REQUEST_DELAY, _season_slug

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ratings-bot/1.0)"}


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


def tt_classes(soup, limit=20) -> None:
    c = Counter()
    for tag in soup.find_all(class_=True):
        for cls in tag.get("class", []):
            if cls.startswith("tt-") and not any(
                skip in cls for skip in ("langswitch", "footer", "nav", "banner", "ad-")
            ):
                c[f"{tag.name}.{cls}"] += 1
    for name, n in c.most_common(limit):
        print(f"      {n:>4}  {name}")


def main() -> None:
    season = sys.argv[1] if len(sys.argv) > 1 else "2025-26"
    slug = _season_slug(season)
    print(f"Structure report for {season} ({slug})")

    url = f"{BASE_URL}/{LEAGUE}/Fixtures/{slug}/Division_Four"
    print(f"\n=== Fixtures — Division_Four ===\n    {url}")
    html = get(url)
    if not html:
        return
    soup = BeautifulSoup(html, "html.parser")
    tt_classes(soup)

    # A played fixture has a score; find one and show the whole row.
    rows = soup.find_all("tr")
    played = None
    for row in rows:
        score_cell = row.find("td", class_="tt-fixture-score")
        if score_cell and re.search(r"\d\s*[-–]\s*\d", score_cell.get_text()):
            played = row
            break

    if played is None:
        print("\n    no played fixture found on this page")
        return

    print("\n    a played fixture row, cell by cell:")
    for cell in played.find_all("td"):
        classes = " ".join(cell.get("class", []))
        text = re.sub(r"\s+", " ", cell.get_text(" ", strip=True))[:70]
        link = cell.find("a")
        href = (link.get("href") or "")[:90] if link else ""
        print(f"      [{classes:24}] {text!r}")
        if href:
            print(f"        -> {href}")

    # Follow whatever the score links to — the match detail.
    score_link = played.find("td", class_="tt-fixture-score").find("a")
    if not score_link:
        score_link = played.find("a", href=re.compile(r"Match|Card|Result", re.I))
    if not score_link:
        print("\n    the score does not link anywhere — no match card?")
        return

    href = score_link["href"]
    card_url = href if href.startswith("http") else BASE_URL + href
    print(f"\n=== Match detail ===\n    {card_url}")
    card = get(card_url)
    if not card:
        return
    csoup = BeautifulSoup(card, "html.parser")
    tt_classes(csoup, 24)
    print(f"    tables: {len(csoup.find_all('table'))}, rows: {len(csoup.find_all('tr'))}")
    print(f"    player links: {len(csoup.find_all('a', href=re.compile(r'/Results/Player')))}")
    print("\n    first 8 rows of the detail:")
    for row in csoup.find_all("tr")[:8]:
        cells = [re.sub(r"\s+", " ", c.get_text(" ", strip=True))[:26]
                 for c in row.find_all(["td", "th"])]
        if any(cells):
            print(f"      {cells}")


if __name__ == "__main__":
    main()
