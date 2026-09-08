# Season handling

Updated September 2026, when the 2026/27 division and team lists went up but
fixtures and confirmed team members had not.

The app now carries ratings across seasons. Most of what this file originally
listed is done; what remains is at the bottom.

## How multiple seasons work

**Matches know their season.** `Match.season` is `"2025-26"`, `"2026-27"` and so
on, defaulting to `"2025-26"` so caches written before this existed still load.
`merge_matches` deduplicates on `(season, match_id)`, because match IDs are only
known to be unique within a season.

**Scraping covers every known season.** `scraper.SEASONS` lists them oldest
first; the last is current. `--update` fetches all of them, so last season's
completed results and the new season's trickle both land in one pass. A season
whose pages are not up yet 404s and is reported as "not published yet" rather
than as an error.

**Ratings carry forward, they are not recomputed from scratch.** Each season is
converged on its own, seeded from the rating each player finished the previous
season on. New players get their division's seed. Someone who sits a season out
keeps their rating, team and division exactly. Match counts accumulate across
seasons, so an established player stays on the lower K-factor instead of
reverting to provisional.

This matters: replaying every season from division seeds would give old results
permanent weight, and a promotion would retroactively rewrite a player's
history by changing the division they are seeded from.

**Rosters carry forward too.** A team that has not played yet this season keeps
the squad it last fielded, and the app says so — the Select tab's availability
list reads "Squads are last season's — 2025/26 — until new results come in".
Once real matches arrive, the current season's roster takes over automatically.

## Division structure before fixtures exist

Divisions and teams are published before any fixtures, so there are no matches
to infer structure from. `data/teams_<season>.json` carries it:

```json
{
  "season": "2026-27",
  "teams": {
    "Apex 4": 3,
    "Apex 5": 5
  }
}
```

When this file exists it defines the league for that season: only its teams
appear, each in the division it names, with rosters carried from the last
season they played. Player divisions follow their team's, so a promoted side
and its players do not disagree.

Delete the file once real fixtures are being scraped — the structure then comes
from the matches themselves. Note the local server caches its payload at
startup, so restart it after editing the file.

## Still to do

1. **Populate `data/teams_2026-27.json`** with the real divisions and teams.
   `probe_season.py` reports what each section of the new season's pages
   contains:

   ```bash
   .venv/bin/python3 probe_season.py 2026-27
   .venv/bin/python3 probe_season.py 2026-27 Division_Three   # just one
   ```

   It tries the Fixtures, Tables and Results sections and prints HTTP status,
   page title, and any team links it finds. If no section yields team names,
   the layout differs from 2025/26 and the parser needs adjusting.

2. **Confirm the URL slug.** `_season_slug` assumes `Winter_2026-27`. The probe
   will 404 on every section if that is wrong.

3. **Confirm match IDs do not collide across seasons.** Keying on
   `(season, match_id)` makes a collision harmless, but it is worth knowing.

4. **Confirm fixtures parse once published.** `_parse_matches` expects the
   2025/26 layout — `div.home` / `div.away`, `div.playerName`, a `(n)` score
   and a `/MatchCard/` link. Run `check_doubles.py` on the first real results
   to confirm the 9 singles + 1 doubles format still holds.

5. **Consider regressing carried ratings toward the division mean.** A half
   step toward it at a season boundary is common practice and stops a player
   who barely played carrying a noisy rating into a new season. Not implemented
   — it is a judgement call, not an oversight.

## Open questions

- Which division is Apex 4 in for 2026/27, and which side is the feeder? The
  app detects club-mates from the team name and defaults to the side directly
  below.
- What is the points target in the new division? The Select tab defaults to
  7.0 of 10 and is editable.
