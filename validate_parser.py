"""Check the new parser against matches the old one already parsed.

The 2025/26 season is finished, parsed and cached, and the redesigned site
still serves it — so re-parsing it with the new code and diffing against the
cache says whether the new parser is right, without waiting for 2026/27
results to accumulate.

    .venv/bin/python3 validate_parser.py [division] [sample]
"""

import sys
import time

import requests

from cache import load_matches
from parser_v2 import build_match, parse_fixtures, parse_match_card
from scraper import BASE_URL, DIVISION_NAMES, LEAGUE, REQUEST_DELAY, _season_slug

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ratings-bot/1.0)"}
SEASON = "2025-26"


def get(url: str) -> str | None:
    r = requests.get(url, headers=HEADERS, timeout=30)
    time.sleep(REQUEST_DELAY)
    return r.text if r.status_code == 200 else None


def main() -> None:
    division = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    sample = int(sys.argv[2]) if len(sys.argv) > 2 else 10

    cached = {m.match_id: m for m in load_matches()
              if m.season == SEASON and m.division == division and m.match_id}
    print(f"cached {SEASON} Division {division} matches: {len(cached)}")

    slug = _season_slug(SEASON)
    url = f"{BASE_URL}/{LEAGUE}/Fixtures/{slug}/{DIVISION_NAMES[division - 1]}"
    html = get(url)
    if not html:
        print(f"could not fetch {url}")
        raise SystemExit(1)

    fixtures = parse_fixtures(html)
    print(f"played fixtures parsed from the new page: {len(fixtures)}")
    if not fixtures:
        print("PARSER BROKEN: no fixtures found")
        raise SystemExit(1)

    overlap = [f for f in fixtures if f["match_id"] in cached]
    print(f"match ids also in the cache: {len(overlap)} "
          f"(ids {'agree' if overlap else 'DO NOT agree — cannot compare'})")
    to_check = (overlap or fixtures)[:sample]

    agree = disagree = 0
    for fixture in to_check:
        card_html = get(f"{BASE_URL}/{LEAGUE}/Results/MatchCard?matchId={fixture['match_id']}")
        if not card_html:
            print(f"  {fixture['match_id']}: card fetch failed")
            continue
        card = parse_match_card(card_html)
        if not card:
            print(f"  {fixture['match_id']}: card did not parse")
            disagree += 1
            continue
        built = build_match(fixture, card, division, SEASON)
        if not built:
            print(f"  {fixture['match_id']}: no singles found on card")
            disagree += 1
            continue

        old = cached.get(fixture["match_id"])
        if old is None:
            print(f"  {fixture['match_id']}: {built.home.name} {built.home.total_score}"
                  f"-{built.away.total_score} {built.away.name} (not in cache)")
            continue

        problems = []
        if (built.home.total_score, built.away.total_score) != (
            old.home.total_score, old.away.total_score
        ):
            problems.append(
                f"score {built.home.total_score}-{built.away.total_score} "
                f"vs cached {old.home.total_score}-{old.away.total_score}"
            )
        for label, new_side, old_side in (
            ("home", built.home, old.home), ("away", built.away, old.away)
        ):
            if new_side.name != old_side.name:
                problems.append(f"{label} team {new_side.name!r} vs {old_side.name!r}")
            new_wins = {p.name: p.games_won for p in new_side.players}
            old_wins = {p.name: p.games_won for p in old_side.players}
            if new_wins != old_wins:
                problems.append(f"{label} wins {new_wins} vs cached {old_wins}")

        if problems:
            disagree += 1
            print(f"  {fixture['match_id']}: MISMATCH")
            for p in problems:
                print(f"      {p}")
        else:
            agree += 1
            print(f"  {fixture['match_id']}: agrees "
                  f"({built.home.name} {built.home.total_score}-{built.away.total_score})")

    print(f"\nagree {agree}, disagree {disagree}")
    raise SystemExit(1 if disagree else 0)


if __name__ == "__main__":
    main()
