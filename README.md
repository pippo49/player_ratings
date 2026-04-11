# Central League London ELO Ratings

ELO rating system for table tennis players in the Central London Table Tennis League, based on results from the Winter 2025/26 season.

## What it does

1. **Scrapes** all match results from Divisions 1-7 on [tabletennis365.com](https://www.tabletennis365.com/CentralLondon/Fixtures/Winter_2025-26/Division_Four)
2. **Calculates** an ELO rating for every player using an iterative convergence algorithm
3. **Outputs** ranked tables per division and overall, with search by player, team, or division

## Setup

Requires Python 3.14+ and [uv](https://docs.astral.sh/uv/):

```bash
uv sync
```

## Usage

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
