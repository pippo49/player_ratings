"""Save raw league pages so a parser can be written against the real markup.

The site is only reachable from environments with open internet, so this
exists to run in CI and upload what it finds as an artifact. It fetches one
page of each kind and writes them verbatim.

    .venv/bin/python3 fetch_pages.py 2026-27 out/
"""

import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from scraper import BASE_URL, LEAGUE, REQUEST_DELAY, _season_slug

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ratings-bot/1.0)"}


def save(url: str, out: Path, name: str) -> str | None:
    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
    except Exception as exc:
        print(f"  {name}: request failed — {type(exc).__name__}")
        return None
    finally:
        time.sleep(REQUEST_DELAY)

    print(f"  {name}: HTTP {response.status_code}  {len(response.text)} bytes  {url}")
    if response.status_code != 200:
        return None
    (out / f"{name}.html").write_text(response.text)
    return response.text


def main() -> None:
    season = sys.argv[1] if len(sys.argv) > 1 else "2026-27"
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "pages")
    out.mkdir(parents=True, exist_ok=True)
    slug = _season_slug(season)

    print(f"Fetching {season} pages\n")

    # A division's fixtures, and its table — the two that list teams.
    fixtures = save(f"{BASE_URL}/{LEAGUE}/Fixtures/{slug}/Division_Four", out, "fixtures")
    save(f"{BASE_URL}/{LEAGUE}/Tables/{slug}/Division_Four", out, "tables")

    # Follow the first team link found, to get a squad page.
    if fixtures:
        soup = BeautifulSoup(fixtures, "html.parser")
        team = soup.find("a", href=re.compile(r"/Results/Team/Statistics/"))
        if team:
            href = team["href"]
            url = href if href.startswith("http") else f"{BASE_URL}{href}"
            print(f"\n  following team link: {team.get_text(strip=True)}")
            save(url, out, "team")
        else:
            print("\n  no team link found on the fixtures page")

        card = soup.find("a", href=re.compile(r"/MatchCard/"))
        if card:
            href = card["href"]
            url = href if href.startswith("http") else f"{BASE_URL}{href}"
            print(f"  following match card link")
            save(url, out, "matchcard")
        else:
            print("  no match card link found (nothing played yet?)")

    print(f"\nSaved to {out}/")
    for f in sorted(out.iterdir()):
        print(f"  {f.name}  {f.stat().st_size} bytes")


if __name__ == "__main__":
    main()
