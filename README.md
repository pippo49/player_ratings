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

A mobile-first web front end covering the same lookups, plus a lineup planner.

```bash
.venv/bin/python3 -m webapp.server            # http://localhost:8000
.venv/bin/python3 -m webapp.server --port 9000
```

On startup it prints two addresses — one for this machine and one for your
phone. Open the second on a phone connected to the same Wi-Fi. On iOS,
*Share → Add to Home Screen* gives it an icon and a full-screen window.

### Tabs

| Tab | Replaces | What it does |
|-----|----------|--------------|
| **Players** | `main.py "name"`, `-d N` | Search by player or team name, filter by division, toggle to rated players only (15+ matches). Tap a player for rank, win rate and singles record. |
| **Teams** | `main.py -t "team"` | Search teams, ranked by the average of their top three. Tap a team for its full squad. |
| **Select** | — | Pick the team you captain, mark who is available, and project the season against a promotion target. |

The refresh button in the header runs the same scrape as `--update` /
`--refresh`, reporting progress per division while it runs and recalculating
ratings when it finishes.

### Match format and scoring

A team match is **9 singles plus 1 doubles**, so 10 points are on offer and
5–5 is a draw. The scraped pages give each player's singles wins and the
team's total score, so the doubles point is recovered as the difference:

```
doubles_point = total_score - sum(singles won by that team's players)
```

That should always be 0 or 1. Run `check_doubles.py` after a scrape to
confirm it holds; the Select tab shows a warning if it does not.

Note that `elo.py` rates **singles only** — the doubles point is not fed back
into player ratings, because the scraped data does not say which two players
formed the pair.

### The Select tab

Three things, in order:

**Call-ups.** Lower sides from the same club whose players you can draw on.
The side directly below is included by default; tick others on if your league
allows it.

**Season outlook.** Your strongest available three against every other team
in your division, each assumed to field its best three. Shows expected points
per fixture, the season average, and whether that clears the promotion target
(default 7.0 of 10, editable).

**A single fixture.** One opponent broken down: expected points, chance of
winning the team match, the split between the 9 singles and the doubles, and
a head-to-head grid.

### Why there is no lineup optimiser

Because all nine singles are a round robin, expected points decompose into one
independent term per selected player:

```
E[points] = Σᵢ Σⱼ P(aᵢ beats bⱼ) + P(doubles)  =  Σᵢ f(aᵢ) + P(doubles)
```

Each `f(aᵢ)` depends only on that player's rating and the fixed opposing trio,
and is strictly increasing in rating. So the trio maximising expected points is
always your three highest-rated available players — searching every combination
provably cannot beat a sort. This was checked empirically across 3,080 team
pairings, optimising for expected points and for win probability separately:
neither ever disagreed with picking the top three by rating.

The interesting question is therefore not *which three* but *whether the three
you have are enough* — which is what the season outlook answers.

### Modelling assumptions

- Each singles is treated as independent, so match odds ignore form and
  head-to-head history on the night.
- The doubles pair is assumed to be each side's strongest two, with pair
  strength modelled as the mean of their singles ratings. On league data this
  is close to a coin flip, so it moves the projection by about half a point.
- Opponents are assumed to field their strongest three, which is a
  worst-case read.
- Ratings marked `*` come from fewer than 15 singles and are less certain.

### Planning for 2026/27

Ratings carry over from Winter 2025/26 — the last full season of results —
so the Select tab is usable for the season starting in October. Team and
division labels are also from 2025/26, so a team that has moved up or down
still shows its old division until the new season's results are scraped.

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

Match data is cached locally in `data/matches.json` after the first run. Subsequent runs load from cache instantly. Use `--update` to scrape for new results and merge them into the cache, or `--refresh` to re-download everything from scratch.

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
  - `server.py` — stdlib HTTP server, static files and two JSON endpoints
  - `api.py` — builds the single payload the front end runs on
  - `static/` — `index.html`, `app.js`, `styles.css` (no build step)

The web app adds no dependencies: the server is `http.server` from the
standard library, and the front end is plain JavaScript. Searching, filtering
and the lineup maths all run in the browser over one payload, so the only
requests after load are the refresh button’s.
