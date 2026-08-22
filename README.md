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

The repo ships without that file — run a scrape first to create it:

```bash
.venv/bin/python3 main.py --refresh
git add data webapp/static/ratings.json && git commit -m "Add ratings snapshot"
```

### Using it offline on match day

Host `webapp/static/` on any static host — Cloudflare Pages, Netlify or GitHub
Pages all work, and all are free (note GitHub Pages needs a paid plan while
this repo is private). Open the URL on your phone once, then
*Share → Add to Home Screen*. A service worker caches the whole bundle, so it
opens and works with no signal at the venue.

The service worker needs HTTPS, which every one of those hosts gives you. It
will **not** register over plain `http://` on a LAN address, so the local
server below is for updating data, not for offline use.

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

### Planning for 2026/27

Ratings carry over from Winter 2025/26 — the last full season of results — so
the Select tab is usable for the season starting in October. Team and division
labels are also from 2025/26, so a team that has moved up or down still shows
its old division until the new season's results are scraped.

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

Players are seeded based on the division they have played the most matches in:

| Division | Seed rating |
|----------|-------------|
| 1        | 1950        |
| 2        | 1800        |
| 3        | 1650        |
| 4        | 1500        |
| 5        | 1350        |
| 6        | 1200        |
| 7        | 1050        |

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
- `warne_cup_compare.py` — compares ratings against Warne Cup handicaps
- `check_doubles.py` — verifies the doubles point can be recovered from a scrape
- `webapp/` — the web app
  - `server.py` — stdlib HTTP server for local use and scraping
  - `api.py` — builds the single payload the front end runs on
  - `export.py` — writes that payload to `static/ratings.json` for committing
  - `static/` — the deployable bundle: `index.html`, `app.js`, `styles.css`,
    `sw.js`, `manifest.json`, icons and `ratings.json` (no build step)
- `data/matches.json` — scraped match data, committed

The web app adds no dependencies: the server is `http.server` from the standard
library, and the front end is plain JavaScript. Searching, filtering and the
selection maths all run in the browser over one payload, so a hosted copy needs
no back end at all.
