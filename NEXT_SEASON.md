# Season handling

Updated September 2026, after the 2026/27 division and team lists went up but
before fixtures or confirmed team members followed.

## Where this stands

Sections 2 and 4 of the original plan — season-aware scraping and a carry-over
rating model — are done. `season_transition.py` remains as the bridge for the
gap between seasons, and now stands down on its own.

**Matches know their season.** `Match.season` is `"2025-26"`, `"2026-27"` and
so on, defaulting to `"2025-26"` so caches written before this existed still
load. `merge_matches` deduplicates on `(season, match_id)`, because match IDs
are only known to be unique within a season.

**Scraping covers every known season.** `scraper.SEASONS` lists them oldest
first; the last is current. A season whose pages are not up yet 404s and is
reported as "not published yet".

**Ratings carry forward.** Each season is converged on its own, seeded from the
rating each player finished the previous season on. Replaying every season from
division seeds — the old behaviour — gave old results permanent weight and let
a promotion retroactively rewrite a player's history by changing the division
they were seeded from. Match counts accumulate across seasons, so an
established player stays on the lower K-factor rather than reverting to
provisional. Verified: single-season output is unchanged to a tenth of a point.

**The bridge disables itself.** `_apply_season_overrides` runs only while the
current season has no matches of its own. The moment real 2026/27 results are
scraped, the static division and roster overrides in `season_transition.py`
stop being applied and rosters come from the new season's matches. The payload
carries `projected: true` while the bridge is active, and the app says squads
are projected rather than real.

That makes `season_transition.py` self-retiring rather than something anyone
has to remember to delete — but it should still be deleted once 2026/27 is
properly underway, since a stale override map is a trap if it ever gets
switched back on.

## Still to do

1. **Replace the inferred division map with the published one.**
   `DIVISION_OVERRIDES` was computed from the 2025/26 final tables by applying
   promotion and relegation rules. The real 2026/27 divisions are now published,
   so the two should be reconciled — the league does not always follow the
   rules exactly (withdrawals, mergers, teams added). `probe_season.py` reports
   what the new pages contain:

   ```bash
   .venv/bin/python3 probe_season.py 2026-27
   .venv/bin/python3 probe_season.py 2026-27 Division_Five   # just one
   ```

   It tries the Fixtures, Tables and Results sections and prints HTTP status,
   page title, and any team links found.

2. **Confirm the URL slug.** `_season_slug` assumes `Winter_2026-27`. The probe
   will 404 on every section if that is wrong.

3. **Confirm fixtures parse once published.** `_parse_matches` expects the
   2025/26 layout — `div.home` / `div.away`, `div.playerName`, a `(n)` score
   and a `/MatchCard/` link.

4. **Fill in rosters as they are confirmed.** `ROSTER_OVERRIDES` currently
   holds Apex 4 only; every other team keeps its 2025/26 squad. Add teams as
   their squads become known, or leave them — they self-correct once results
   arrive.

5. **Consider regressing carried ratings toward the division mean.** A half
   step toward it at a season boundary is common practice and stops a player
   who barely played carrying a noisy rating into a new season. Not
   implemented — a judgement call, not an oversight.

## Verified against real data

937 matches from Winter 2025/26, September 2026:

- The 9 singles + 1 doubles format holds on every match, no anomalies, so the
  conversion between a match-points target and a singles target is sound.
- The home side wins the doubles 51.6% of the time.
