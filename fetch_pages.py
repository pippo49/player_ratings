"""Report the structure of league pages, for writing parsers against.

The league site is only reachable from environments with open internet, and
build artifacts from those runs are not reachable either, so this prints a
compact structural summary to stdout where it can be read back from the job
log. Deliberately bounded: histograms and short snippets, not whole pages.

    .venv/bin/python3 fetch_pages.py 2026-27
"""

import re
import sys
import time
from collections import Counter

import requests
from bs4 import BeautifulSoup

from scraper import BASE_URL, LEAGUE, REQUEST_DELAY, _season_slug

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ratings-bot/1.0)"}

# What the 2025/26 parser relied on. Any of these at zero means it is broken.
LEGACY = {
    "div.home": ("div", "home"),
    "div.away": ("div", "away"),
    "div.playerName": ("div", "playerName"),
    "div.score": ("div", "score"),
}


def get(url: str) -> str | None:
    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
    except Exception as exc:
        print(f"    request failed — {type(exc).__name__}: {exc}")
        return None
    finally:
        time.sleep(REQUEST_DELAY)
    print(f"    HTTP {response.status_code}, {len(response.text)} bytes")
    return response.text if response.status_code == 200 else None


def describe(html: str, label: str) -> BeautifulSoup:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.find("title")
    print(f"    title: {title.get_text(strip=True) if title else '(none)'}")

    print("    legacy selectors:", ", ".join(
        f"{name}={len(soup.find_all(tag, class_=cls))}"
        for name, (tag, cls) in LEGACY.items()
    ))

    hrefs = Counter()
    for a in soup.find_all("a", href=True):
        # Group by the first three path segments, which identify the kind.
        parts = [p for p in a["href"].split("?")[0].split("/") if p][:4]
        hrefs["/" + "/".join(parts)] += 1
    print("    link shapes:")
    for shape, n in hrefs.most_common(12):
        print(f"      {n:>4}  {shape}")

    classes = Counter()
    for tag in soup.find_all(class_=True):
        for c in tag.get("class", []):
            classes[f"{tag.name}.{c}"] += 1
    print("    common classes:")
    for c, n in classes.most_common(20):
        print(f"      {n:>4}  {c}")
    return soup


def main() -> None:
    season = sys.argv[1] if len(sys.argv) > 1 else "2026-27"
    slug = _season_slug(season)
    print(f"Structure report for {season} ({slug})")

    for section in ("Fixtures", "Tables"):
        url = f"{BASE_URL}/{LEAGUE}/{section}/{slug}/Division_Four"
        print(f"\n=== {section} — Division_Four ===\n    {url}")
        html = get(url)
        if not html:
            continue
        soup = describe(html, section)

        if section == "Fixtures":
            body = soup.find("main") or soup.find("body")
            text = re.sub(r"\s+", " ", body.get_text(" ", strip=True))[:900]
            print(f"    text sample: {text}")

            # Follow whatever looks like a team link, whatever its shape.
            team = soup.find("a", href=re.compile(r"/Team|/Results/Team"))
            if team:
                href = team["href"]
                team_url = href if href.startswith("http") else BASE_URL + href
                print(f"\n=== Team page — {team.get_text(strip=True)} ===\n    {team_url}")
                team_html = get(team_url)
                if team_html:
                    tsoup = describe(team_html, "team")
                    tbody = tsoup.find("main") or tsoup.find("body")
                    ttext = re.sub(r"\s+", " ", tbody.get_text(" ", strip=True))[:900]
                    print(f"    text sample: {ttext}")
            else:
                print("\n    no team link found on the fixtures page")


if __name__ == "__main__":
    main()
