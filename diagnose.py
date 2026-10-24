"""Why is the scrape finding nothing? Writes a report the sandbox can read.

Job logs and build artifacts both come from blob storage, which the
development sandbox is not allowed to reach, so a diagnostic that prints is
a diagnostic nobody can read. This writes to a file the workflow commits,
which is the one channel that works in both directions.

    python diagnose.py 2026-27
"""

import sys
from datetime import date
from pathlib import Path

from cache import load_matches
from parser_v2 import parse_fixtures
from scraper import CURRENT_SEASON, _fetch_html, _fixtures_url, division_slugs

OUTPUT = Path("data") / "diagnosis.txt"


# Headers are deliberately left exactly as the scraper sends them. The point
# is to read the refusal, not to get around it: what the server says when it
# says no is the only evidence of why, and it is what the league will need.
def refusal_detail(url: str, lines: list[str]) -> None:
    import requests

    lines.append(f"what the server says when it refuses: {url}")
    try:
        r = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; ratings-bot/1.0)"},
            timeout=30,
        )
    except Exception as e:  # noqa: BLE001 - the reason is the diagnosis
        lines.append(f"    no response at all: {type(e).__name__}: {e}")
        lines.append("")
        return

    lines.append(f"    status {r.status_code} {r.reason}, {len(r.content)} bytes")
    for key in ("server", "cf-ray", "cf-mitigated", "retry-after", "x-powered-by",
                "content-type", "set-cookie", "x-cache", "via", "x-amzn-waf-action"):
        if key in r.headers:
            lines.append(f"    {key}: {r.headers[key][:160]}")
    body = " ".join(r.text.split())
    lines.append(f"    body: {body[:600]}")
    lines.append("")


def main(season: str) -> None:
    cached = {m.match_id for m in load_matches() or [] if m.season == season}
    lines = [
        f"diagnosis for {season}, written {date.today()}",
        f"cached match ids for this season: {len(cached)}",
        "",
    ]

    refusal_detail(_fixtures_url("Division_Four", season), lines)

    for division_name, division in division_slugs(season):
        url = _fixtures_url(division_name, season)
        try:
            html = _fetch_html(url)
        except Exception as e:  # noqa: BLE001 - the reason is the diagnosis
            lines.append(f"{division_name}: FETCH FAILED {type(e).__name__}: {e}")
            continue

        fixtures = parse_fixtures(html, season)
        rows = html.count("<tr")
        team_cells = html.count("tt-fixture-teamcell")
        score_cells = html.count("tt-fixture-score")
        dates = [f["date"] for f in fixtures if f["date"]]
        no_id = sum(1 for f in fixtures if not f["match_id"])
        unseen = [f for f in fixtures if f["match_id"] and f["match_id"] not in cached]

        lines.append(
            f"{division_name} (div {division}): {len(html)} bytes, {rows} rows, "
            f"{team_cells} team cells, {score_cells} score cells"
        )
        lines.append(
            f"    played fixtures parsed: {len(fixtures)}"
            f"  without a match id: {no_id}"
            f"  not yet cached: {len(unseen)}"
        )
        if dates:
            lines.append(f"    dates run {min(dates)} to {max(dates)}")
        for f in sorted(fixtures, key=lambda f: f["date"] or date.min)[-4:]:
            seen = "cached" if f["match_id"] in cached else "NEW"
            lines.append(
                f"      {f['date']}  {f['home']} {f['home_score']}-{f['away_score']} "
                f"{f['away']}  id={f['match_id'] or '-'}  {seen}"
            )
        lines.append("")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else CURRENT_SEASON)
