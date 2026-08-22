# Moving to the 2026/27 season

Written August 2026, while the app only had Winter 2025/26 data. The app is
correct for a single season; carrying two seasons needs the work below. Nothing
here is urgent until the 2026/27 fixture pages go up on tabletennis365.

**Update, August 2026:** the 2025/26 season finished (last match 24 April
2026) and Apex 4's 2026/27 squad is already confirmed, so a stopgap for
section 3 landed early: `season_transition.py` holds a static
promotion/relegation division map (computed from the real final tables) and
a roster override for Apex 4, applied in `webapp/api.py::_apply_season_overrides`.
This covers division labels for every team and the roster for Apex 4 only —
every other team's roster is still last season's until real 2026/27 results
come in. It is a hand-maintained bridge, not the season-aware rewrite below;
once section 2 (season-aware scraping) is done, `season_transition.py` and
its call site should be deleted.

The short version: the caching and merging already work across seasons, but
the **scraper is pinned to one season**, **team and division labels go stale**,
and the **rating model is not actually carry-over**. The third is a design
decision, not a bug.

## 1. Check these first, before changing anything

The new pages may not look how we assume.

- **URL slug.** `scraper.py` builds `/{LEAGUE}/Fixtures/{SEASON}/{division}`
  with `SEASON = "Winter_2025-26"`. Confirm the new one is `Winter_2026-27` and
  not something else.
- **Division count.** `DIVISION_NAMES` lists seven. Confirm that still holds,
  and that `DIVISION_SEED` in `elo.py` covers every division in use.
- **Match ID collisions.** `merge_matches` deduplicates on `match_id` alone. If
  IDs restart per season, old and new matches will silently overwrite each
  other. Check a few IDs across both seasons before merging anything.
- **Match format.** Run `check_doubles.py` on the first new results to confirm
  it is still 9 singles + 1 doubles. The singles/points conversion in the
  Select tab depends on it.

## 2. Season-aware scraping

`SEASON` is a module constant, so `--update` will keep re-fetching 2025/26
forever and report nothing new.

- Add a `season` field to `Match` in `models.py`, defaulting to `"2025-26"` so
  existing cached data still loads.
- Round-trip it in `cache.py` (`_match_to_dict` / `_dict_to_match`).
- Let `scrape_all_divisions` take a season, and scrape both while the new one
  is short of data.

The `season` field is a prerequisite for section 3 — without it there is no way
to tell which matches are current.

## 3. Scope rosters and labels to the current season

This is the one that will actually bite during selection. Simulated with Apex 4
promoted to Division 3 and two Apex 5 players moving up, three weeks into the
new season the app still showed:

- Apex 4 as **Division 4**, because `_team_divisions` takes the most-played
  division across *all* data
- an Apex 4 roster containing both players who had left and players who had
  joined, because `_rosters` pools every match ever

So the Select tab would offer players who are no longer at the club and omit
ones who are. Fix in `webapp/api.py`:

- `_rosters` and `_team_divisions` should consider current-season matches only.
- A player's `team` and `division` should be their most-played **this** season,
  falling back to last season only if they have not played yet.
- Ratings should still be computed over both seasons — it is only the labels
  and rosters that should be current-season.

## 4. Decide the rating model

`calculate_ratings` reseeds every player from their division and replays every
match from scratch on each run. Consequences:

- 2025/26 results keep full weight indefinitely.
- `K` drops to 32 after 15 team matches, so by October everyone is
  "established" and new results move ratings slowly — exactly when you most
  want them to move.
- A promoted player's seed can flip mid-season once their new division becomes
  their most-played, shifting their whole history retroactively.

Three options:

**A. Leave it.** Simplest. Old form never fades, new form arrives slowly.

**B. Carry-over seeding (recommended).** Freeze the final 2025/26 ratings and
use them as each player's 2026/27 starting rating, then rate only new matches
on top with a fresh K schedule. This is what "keep the stats and update as
results come in" actually means. Needs:

- a one-off export of final ratings, e.g. `data/seed_ratings_2026-27.json`
- `_seed_ratings` to prefer a carried-over rating, falling back to division
  seeding for players with no history
- a decision on whether to regress toward the division mean (a half-step
  toward it is common, and stops a player who barely played carrying a noisy
  rating into a new season)

**C. Pooled with decay.** Keep replaying everything but weight recent matches
more. More faithful than A, more code than B, and harder to explain.

Go with B unless there is a reason not to. It also removes the retroactive
reseeding problem in A.

## 5. Cosmetics

- `SEASON_LABEL` in `webapp/api.py` is hardcoded to `"Winter 2025/26"`. Derive
  it from the data instead.
- The README's "Planning for 2026/27" section describes the stale-label
  behaviour as a known limitation. Remove it once section 3 is done.

## 6. How to test

Real data will be thin for weeks, so test with a synthetic second season:
generate a partial 2026/27 on top of the real 2025/26 cache, with a team
promoted and a couple of players moved between club sides, then check that

- ratings move sensibly with a few new results rather than barely at all
- team and division labels reflect the new season
- the Select tab's squad matches who is actually at the club now
- old and new matches both survive a `--update`

## 7. Open questions

- Which rating model — A, B or C?
- Which division is Apex 4 in, and which side is the feeder? The app detects
  club-mates from the team name and defaults to the side directly below.
- What is the points target in the new division? The Select tab defaults to
  7.0 of 10 and is editable, but the default may want changing.
