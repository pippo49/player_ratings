# Central League London ELO Ratings

ELO rating system for table tennis players in the Central London Table Tennis League, based on results from the Winter 2025/26 season.

## What it does

1. **Scrapes** all match results from Divisions 1-7 on [tabletennis365.com](https://www.tabletennis365.com/CentralLondon/Fixtures/Winter_2025-26/Division_Four)
2. **Calculates** an ELO rating for every player using an iterative convergence algorithm
3. **Outputs** ranked tables per division and overall, with search by player, team, or division

There are two front ends over the same engine: a command line tool (`main.py`)
and a phone-friendly web app (`webapp/`).

## Setup

Requires Python 3.14+ and [uv](https://docs.astral.sh/uv/):

```bash
uv sync
```

## Web app

A mobile-first web front end covering the same lookups, plus season planning.

The whole app is static files plus one data file, `webapp/static/ratings.json`,
which is **committed to the repo**. That means it can be hosted anywhere, works
offline once loaded, and updates by re-running a scrape and committing the
result.

The repo ships without that file. Either run a scrape locally:

```bash
.venv/bin/python3 main.py --refresh
git add data webapp/static/ratings.json && git commit -m "Add ratings snapshot"
```

…or let Actions do it: once Pages is enabled, Actions → Publish → **Run
workflow** scrapes, commits the snapshot and deploys, with no terminal
involved. The whole setup can be done from a browser that way.

### Publishing it

`.github/workflows/publish.yml` scrapes the league every Monday, commits any
new results, and publishes `webapp/static/` to GitHub Pages. It also publishes
on any push to `master` that touches the bundle, and can be run on demand from
the Actions tab. One-time setup:

1. The repository must be **public** — Pages needs a paid plan on private repos.
   (Actions minutes are also unlimited on public repos; private repos get 2,000
   a month, which is still far more than a weekly scrape uses.)
2. Settings → Pages → Source: **GitHub Actions**.

With that in place the weekly refresh needs nothing from you — the site updates
itself and phones pick it up next time they have signal. Running `--update`
from a terminal still works and still publishes, for when you want results
immediately rather than waiting for Monday.

Scraping and deploying live in one workflow because a push made with the
default `GITHUB_TOKEN` does not trigger other workflows, so a separate deploy
workflow would never fire after the scrape commits. The bundle is uploaded as
an artifact rather than served directly, because Pages can only serve a repo's
root or `/docs`.

To change the schedule, edit the `cron` line; to stop it, disable the workflow
in the Actions tab. Cloudflare Pages and Netlify are alternatives that work
with private repos on their free tiers.

### Using it offline on match day

Open the published URL on your phone once, then *Share → Add to Home Screen*.
A service worker caches the whole bundle, so it opens and works with no signal
at the venue. It is network-first, so with signal you always get the latest
ratings and it only falls back to the cached copy when there is none.

The service worker needs HTTPS, which every static host gives you. It will
**not** register over plain `http://` on a LAN address, so the local server
below is for updating data, not for offline use. If your venues have signal you
do not need it at all — delete `sw.js`, `manifest.json` and the registration
block in `index.html` and everything else works unchanged.

### Running it locally

```bash
.venv/bin/python3 -m webapp.server            # http://localhost:8000
.venv/bin/python3 -m webapp.server --port 9000
```

On startup it prints an address for this machine and one for your phone on the
same Wi-Fi. In this mode the refresh button appears and ratings are served from
a live calculation rather than the committed snapshot.

### Updating the data

Any fresh fetch rewrites `webapp/static/ratings.json` automatically:

```bash
.venv/bin/python3 main.py --update      # scrape, then re-export
.venv/bin/python3 -m webapp.export      # re-export from the cache alone
git add data webapp/static/ratings.json && git commit -m "Update ratings" && git push
```

The refresh button in the running web app does the same thing, and says so when
the snapshot has been rewritten. Pushing is what publishes it — the hosted site
redeploys from the commit, and phones pick it up next time they have signal.

### Tabs

| Tab | Replaces | What it does |
|-----|----------|--------------|
| **Players** | `main.py "name"`, `-d N` | Search by player or team name, filter by division, toggle to rated players only (15+ matches). Tap a player for rank, win rate and singles record. |
| **Teams** | `main.py -t "team"` | Search teams, ranked by the average of their top three. Tap a team for its full squad. |
| **Select** | — | Pick the team you captain, mark who is available, and project the season against a promotion target. |

### Match format and scoring

A team match is **9 singles plus 1 doubles**, so 10 points are on offer and
5–5 is a draw.

**The doubles is not modelled.** The scraped data does not say which two
players formed the pair, so predicting it would be inventing a number. The app
projects the 9 singles and converts your target by assuming the doubles splits
evenly: a 7.0 of 10 target becomes 6.5 of 9 singles.

That conversion depends on the format being what we think it is. The doubles
point should always be recoverable as a team's total minus its singles wins,
split 0/1 between the sides. Run `check_doubles.py` after a scrape to confirm;
the Select tab warns if it does not hold.

`elo.py` rates singles only, for the same reason.

### The Select tab

**Call-ups.** Lower sides from the same club whose players you can draw on. The
side directly below is included by default; tick others on if your league
allows it.

**Season outlook.** Your strongest available three against every other team in
your division, each assumed to field its best three. Shows expected singles per
fixture, the season average, and whether that clears the target, with fixtures
sorted hardest-first.

**A single fixture.** One opponent broken down, with a head-to-head grid.

### Why there is no lineup optimiser

Because all nine singles are a round robin, expected singles decompose into one
independent term per selected player:

```
E[singles] = Σᵢ Σⱼ P(aᵢ beats bⱼ)  =  Σᵢ f(aᵢ)
```

Each `f(aᵢ)` depends only on that player's rating and the fixed opposing trio,
and is strictly increasing in rating. So the best trio is always your three
highest-rated available players — searching every combination provably cannot
beat a sort. This was checked across 3,080 team pairings, optimising for
expected score and for win probability separately; neither ever disagreed.

The interesting question is therefore not *which three* but *whether the three
you have are enough*, which is what the season outlook answers.

### Modelling assumptions

- Each singles is treated as independent, so projections ignore form and
  head-to-head history on the night.
- Opponents are assumed to field their strongest three, which is a worst-case
  read.
- Ratings marked `*` come from fewer than 15 singles and are less certain.
- Nothing accounts for league rules on how often a player may be called up.

### Seasons

Ratings carry across seasons. Each season is converged on its own, seeded from
the rating each player finished the previous one on, rather than replaying
every season from division seeds. A player who sits a season out keeps their
rating, team and division; a new player gets their division's seed. Match
counts accumulate, so nobody reverts to provisional at a season boundary.

`scraper.SEASONS` lists the seasons to fetch, oldest first, with the last being
current. `--update` fetches all of them, so last season's completed results and
the new season's trickle land in one pass. A season whose pages are not up yet
is reported as "not published yet" rather than as an error.

Rosters and divisions come from the current season once it has results. Until
then `season_transition.py` supplies the known division moves and any confirmed
roster changes, and the app marks itself as showing a projection. That bridge
disables itself automatically as soon as real results for the current season
arrive — see `NEXT_SEASON.md`.


## Command line usage

```bash
# Full league tables (overall top 20 + top 10 per division)
# Uses cached data if available, otherwise scrapes all divisions
.venv/bin/python3 main.py

# Search for a player by name (case-insensitive, partial match)
.venv/bin/python3 main.py "boom"
.venv/bin/python3 main.py "bryan kwan"

# Show full table for a specific division
.venv/bin/python3 main.py --division 4
.venv/bin/python3 main.py -d 1

# Search by team name (case-insensitive, partial match)
.venv/bin/python3 main.py --team "fusion 5"
.venv/bin/python3 main.py -t "apex"

# Check for new matches and add them to the cache
.venv/bin/python3 main.py --update

# Full re-download of all matches (replaces cache)
.venv/bin/python3 main.py --refresh
```

### Caching

Match data lives in `data/matches.json` and is **committed to the repo** once
you have run a scrape, so a fresh clone works without scraping again. Use
`--update` to scrape for
new results and merge them in, or `--refresh` to re-download everything. Either
one also rewrites `webapp/static/ratings.json`; commit both to publish.

### Output columns

| Column | Meaning |
|--------|---------|
| Rank   | Position in the current table |
| Name   | Player name |
| Team   | Team the player has played most matches for |
| Div    | Division the player has played most matches in |
| Rating | ELO rating |
| M      | Number of singles matches played (3 per team match) |
| Win%   | Singles match win percentage |

Players with fewer than 15 singles matches are flagged with `*` to indicate a less reliable rating.

## How the ratings work

### Data source

Each team match consists of 9 singles matches (3 players per side, round-robin). Each singles match is best of 5 sets, each set to 11 points (win by 2). The scraped data gives each player's singles wins (0-3) per team match.

### Initial seeding

A player with no rating history is seeded from the division they have played
the most matches in. Anyone who played a previous season carries their rating
forward instead, so this only ever applies to genuine newcomers.

The ladder is season-specific, because the league restructured for 2026/27 by
adding a Premier division above Divisions One to Seven — a division number no
longer means what it meant in 2025/26. `elo.seed_for(season, division)` picks
the right one.

| Division | 2025/26 | 2026/27 |
|----------|---------|---------|
| Premier  | —       | 1850    |
| 1        | 1800    | 1750    |
| 2        | 1700    | 1650    |
| 3        | 1600    | 1550    |
| 4        | 1500    | 1450    |
| 5        | 1400    | 1350    |
| 6        | 1300    | 1250    |
| 7        | 1200    | 1150    |

Both are 100 points per division. The 2025/26 ladder took Division 4 as a 1500
midpoint, and proved well calibrated — every division's median player finished
within 21 points of the seed they started from. The 2026/27 ladder is anchored
at 1850 for the Premier, fitted to the median rating of the players actually
placed in each division; that gives a mean error of 30 points, against 98 for
carrying the old ladder up a division.

Seeding a newcomer too high does not just mislabel them — it leaks into every
opponent's rating, because beating an over-rated player pays out too much.

### ELO calculation

The system uses a standard ELO formula. For each team match, every player is compared individually against each of their 3 opponents:

```
expected_score = 1 / (1 + 10^((opponent_rating - player_rating) / 400))
```

The expected scores from all 3 opponents are summed and normalised. The rating update is:

```
rating_change = K * (actual_fraction - expected_fraction)
```

Where `actual_fraction = singles_won / 3` and `expected_fraction = sum(expected per opponent) / 3`.

This means beating a higher-rated opponent gains more points than beating a lower-rated one, matching the core principle of ELO in chess.

### Iterative convergence

Because early matches in the season are evaluated against division-seeded ratings (which may not reflect true skill), the algorithm runs multiple passes over the full season. Each pass replays all matches chronologically using the ratings from the previous pass. This repeats until ratings stabilise (max change < 0.5 per pass, up to 20 iterations).

### Parameters

- **K-factor**: 32 (controls how much a single team match can shift a rating)
- **Minimum matches**: 15 singles matches (players with fewer are flagged with `*` in the output)

## Project structure

- `main.py` — CLI entry point, prints tables and handles search
- `scraper.py` — fetches and parses fixture pages from tabletennis365.com
- `elo.py` — ELO rating engine with iterative convergence
- `models.py` — data classes (`Match`, `TeamResult`, `PlayerResult`)
- `cache.py` — JSON serialisation and match deduplication
- `check_doubles.py` — verifies the doubles point can be recovered from a scrape
- `webapp/` — the web app
  - `server.py` — stdlib HTTP server for local use and scraping
  - `api.py` — builds the single payload the front end runs on
  - `export.py` — writes that payload to `static/ratings.json` for committing
  - `static/` — the deployable bundle: `index.html`, `app.js`, `styles.css`,
    `sw.js`, `manifest.json`, icons and `ratings.json` (no build step)
- `data/matches.json` — scraped match data, committed
- `.github/workflows/publish.yml` — weekly scrape and GitHub Pages deploy
- `NEXT_SEASON.md` — what needs changing when the 2026/27 fixtures go up

The web app adds no dependencies: the server is `http.server` from the standard
library, and the front end is plain JavaScript. Searching, filtering and the
selection maths all run in the browser over one payload, so a hosted copy needs
no back end at all.
