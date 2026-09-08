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
## The 2026/27 restructure

The league took 94 entries and moved from seven tiers to eight: a Premier
division above Divisions One to Seven, each capped at 12 teams. The published
structure returns exactly 94 teams, which matches.

That shifts what a division number means. Comparing the median team's
top-three average rating in each new division against each old one:

| 2026/27 | median top-3 | closest 2025/26 equivalent |
|---------|--------------|----------------------------|
| Premier | 1878 | Division 1 (1856) |
| Division 1 | 1777 | Division 2 (1768) |
| Division 2 | 1709 | Division 3 (1680) |
| Division 3 | 1621 | Division 3–4 |
| Division 4 | 1511 | Division 5 (1484) |
| Division 5 | 1417 | Division 6 (1388) |
| Division 7 | 1224 | Division 7 (1266) |

**When judging a target or a season, compare a 2026/27 division against the
2025/26 division one below it, not the one with the same number.**

## Division seeds

The medians above are each team's **top three** averaged — not a typical
player. A team's best three sit about 68 points above its division's player
seed, because they are its strongest, not its median. The two numbers are not
comparable directly.

At player level the 2025/26 seeds are near-perfect. The median player in each
division finished within about 20 points of the seed they started from:

| Division | Seed | Median player | Drift |
|---|---|---|---|
| 1 | 1800 | 1794 | −6 |
| 2 | 1700 | 1679 | −21 |
| 3 | 1600 | 1593 | −7 |
| 4 | 1500 | 1484 | −16 |
| 5 | 1400 | 1395 | −5 |
| 6 | 1300 | 1294 | −6 |
| 7 | 1200 | 1193 | −7 |

For 2026/27 they were too generous by roughly half a division, so the ladder
is now season-specific. `elo.SEASON_SEEDS` holds one per season and
`elo.seed_for(season, division)` picks it; the 2025/26 ladder is untouched, so
no existing rating moved.

| 2026/27 | seed | median player | drift |
|---|---|---|---|
| Premier | 1850 | 1796 | +54 |
| Division 1 | 1750 | 1706 | +44 |
| Division 2 | 1650 | 1654 | −4 |
| Division 3 | 1550 | 1533 | +17 |
| Division 4 | 1450 | 1463 | −13 |
| Division 5 | 1350 | 1369 | −19 |
| Division 6 | 1250 | 1300 | −50 |
| Division 7 | 1150 | 1192 | −42 |

Mean error 30 points, against 98 for carrying the old ladder up a division.
Coverage is the weak spot: Division 4 is 9 of 12 teams rated but Division 6
only 3 of 11, and the unrated teams are the new or renamed ones. Twelve teams
were pushed down when the top five divisions were oversubscribed, and those
are strong for their new division, so the true medians are probably a little
above these — the ladder errs low deliberately, since results correct a low
seed upward but an inflated one leaks points to every opponent first.

## Still to do

1. ~~**Fetch the published division map.**~~ Done. `data/teams_2026-27.json`
   holds the real structure — 94 teams, 12 per division, Premier included.
   Re-run it if the league moves anyone:

   ```bash
   .venv/bin/python3 fetch_structure.py 2026-27
   ```

   Or dispatch the publish workflow with `fetch_structure: 2026-27`, which is
   how it was collected — the site is reachable from Actions runners even
   where it is not from a development sandbox.

2. **Reconcile renamed teams.** 29 teams from 2025/26 do not appear under the
   same name in the published structure, and many are renames rather than
   withdrawals — "Clissold 3 Jr" to "Clissold 3", "Fulham Brunswick 4" to
   "Fulham Brunswick 4 Jr". A renamed team loses its carried roster and starts
   empty, and its players keep last season's division badge. Worth a pass
   matching old names to new before the season starts.

3. **Fill in rosters as they are confirmed.** `ROSTER_OVERRIDES` currently
   holds Apex 4 only; every other team keeps its 2025/26 squad. Add teams as
   their squads become known, or leave them — they self-correct once results
   arrive.

4. **Confirm fixtures parse once published.** `_parse_matches` expects the
   2025/26 layout — `div.home` / `div.away`, `div.playerName`, a `(n)` score
   and a `/MatchCard/` link. The `Winter_2026-27` slug is already confirmed
   working by the structure fetch.

5. **Decide on a 2026/27 seed map**, per the section above, before the first
   new player appears in results.

6. **Consider regressing carried ratings toward the division mean.** A half
   step toward it at a season boundary is common practice and stops a player
   who barely played carrying a noisy rating into a new season. Not
   implemented — a judgement call, not an oversight.

## Verified against real data

937 matches from Winter 2025/26, September 2026:

- The 9 singles + 1 doubles format holds on every match, no anomalies, so the
  conversion between a match-points target and a singles target is sound.
- The home side wins the doubles 51.6% of the time.
- The published 2026/27 structure returns 94 teams, matching the league's
  stated entry count.
