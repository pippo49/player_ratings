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

**Results are fetched from your own machine, not from GitHub.** Since
18 October 2026 Cloudflare has answered GitHub's runners with a JavaScript
challenge (`cf-mitigated: challenge`), because they are datacenter IPs. A
scrape from there now fetches nothing however often it runs, so the schedule
has been removed. A home connection is a different profile.

**Since 25 October 2026 a home connection is challenged too**, so for now
the weekly update is done from pages saved in your own browser —
`import_saved.py` parses them and publishes, and never contacts the site:

```bash
uv run python import_saved.py ~/Downloads/tt365 --open   # opens fixtures pages; save each there
uv run python import_saved.py ~/Downloads/tt365 --open   # publishes, opens missing match cards
uv run python import_saved.py ~/Downloads/tt365          # after saving those: publishes the rest
```

Save with Ctrl+S into that one folder; names do not matter. If the league
ever allowlists the scraper or offers a feed, `publish.py` below becomes the
one command again.

One command does the whole loop — fetch, rebuild, commit, push:

```bash
uv run python publish.py
```

GitHub Pages redeploys on the push, so the app has the new results about a
minute later. Options:

| | |
|---|---|
| `publish.py` | results only — the everyday run |
| `publish.py --squads` | also refresh squads; slower, every team page |
| `publish.py --dry-run` | fetch and report, commit nothing |

It stops rather than publishing nothing when the league will not answer, says
how many results came in and what they were, and does nothing at all when
there is nothing new.

`.github/workflows/publish.yml` now only **deploys**: any push to `master`
touching `webapp/static/` publishes the bundle. It can still be run from the
Actions tab for squads, diagnostics or a manual redeploy — it just will not
get past the challenge for results.

One-time setup:

1. The repository must be **public** — Pages needs a paid plan on private repos.
2. Settings → Pages → Source: **GitHub Actions**.

## Running a scrape from your own machine

What you need, once:

1. **Git**, and the repo cloned:
   ```bash
   git clone https://github.com/pippo49/player_ratings.git
   cd player_ratings
   ```
2. **uv**, which fetches the right Python itself:
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh     # macOS / Linux / Pi
   powershell -c "irm https://astral.sh/uv/install.ps1 | iex"   # Windows
   ```
3. **Push access**, so the commit can reach GitHub. Check with `git push`
   before relying on it.

Then, each time:

```bash
cd player_ratings && git pull && uv run python publish.py
```

If the league site challenges your connection too, `publish.py` says so and
changes nothing. That is the answer to whether the datacenter IP was the
trigger, and it is worth knowing either way.

## Weekly update from saved pages

Cloudflare challenges scripted requests from everywhere now, home included,
so `publish.py` cannot fetch. Until the allowlist request is answered, the
pages are saved by hand in a normal browser and `import_saved.py` reads them.
It never contacts the league.

**Save only the divisions you follow.** The work is roughly five pages per
division per week, so this is the difference between an afternoon and ten
minutes. Ratings in the divisions you skip stop moving until you import them;
nothing breaks, and importing them later catches up.

```bash
cd ~/player_ratings && git pull
D=~/tt365 && rm -rf "$D" && mkdir -p "$D"

# 1. the fixtures pages — Ctrl+S each into $D
uv run python import_saved.py "$D" --divisions 3,4,7 --open

# 2. it now lists the match cards it needs; --open puts them in tabs, save each
uv run python import_saved.py "$D" --divisions 3,4,7 --open

# 3. publish
uv run python import_saved.py "$D" --divisions 3,4,7
```

Use `--dry-run` on the first pass to see what it found without writing
anything. `--divisions` takes numbers, with `0` or `prem` for the Premier;
leave it off for the whole league.

Wait for each page to finish loading before saving it: a page saved during
the "Just a moment" check contains the check rather than the results, and the
importer says so by name rather than silently skipping it.

## On a Raspberry Pi, unattended

A Pi on the home connection is the right home for this: always on, and the
residential IP is the whole point. Check the architecture first, because it
decides whether `uv` can fetch a Python for you:

```bash
uname -m
```

- **`aarch64`** (64-bit Raspberry Pi OS, Pi 3 onwards) — `uv` ships builds and
  fetches its own Python. Follow the steps above and you are done.
- **`armv7l`** (32-bit OS) — `uv` has no managed Python build for it. Either
  reflash with 64-bit Raspberry Pi OS, or use the system Python with
  `pip install requests beautifulsoup4` and run `python3 publish.py`
  directly. The code needs nothing newer; only `pyproject.toml` asks for
  3.14, and that is a packaging floor rather than a language requirement.

**Pushing without a password.** cron cannot answer a prompt, so use an SSH
key the Pi holds:

```bash
ssh-keygen -t ed25519 -C "pi-scraper" -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub
```

Add that to GitHub under Settings → SSH and GPG keys, then point the clone at
SSH and check it:

```bash
git remote set-url origin git@github.com:pippo49/player_ratings.git
git push      # should go through with no prompt
```

**The schedule.** Keep it modest — twelve runs a day from one address is what
the scheduled job was doing when Cloudflare started challenging it. Results
are posted in the evening, and captains have 48 hours (Rule 33), so four
spread across the day catches everything without being noticed:

```cron
17 8,13,19,23 * * *  cd /home/pi/player_ratings && /usr/bin/flock -n /tmp/ratings.lock /home/pi/.local/bin/uv run python publish.py >> /home/pi/ratings.log 2>&1
```

- `flock -n` means a run that is still going is never doubled up on.
- The log is append-only and every line is timestamped, so it reads as a
  history. `tail -f ~/ratings.log` while a run happens; `grep -c "new result"
  ~/ratings.log` to see it has been working.
- cron mails you stderr on a non-zero exit, which is the failure case — a
  league refusal, or a push that could not authenticate.

Add the squad refresh weekly rather than daily; rosters change by a player or
two a day and it walks every team page:

```cron
41 7 * * 0  cd /home/pi/player_ratings && /home/pi/.local/bin/uv run python publish.py --squads >> /home/pi/ratings.log 2>&1
```

**Check it is actually running.** The app shows the age of the data in the
results sheet and says so past a day, which is the backstop. For a direct
look:

```bash
tail -20 ~/ratings.log
```

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

- **K-factor**: 48 while provisional, 32 once established (controls how much a
  single team match can shift a rating)
- **Provisional**: fewer than 15 career team matches, *or* fewer than 6 team
  matches so far this season. A carried rating is a stale prior — a summer
  passes and players improve or fall away — so everyone starts a season
  provisional again whatever their career record. Sweeping 3/3 against equals
  moves a provisional player about 22 points and an established one about 15.
- **Minimum matches**: 15 singles matches (players with fewer are flagged with `*` in the output)

## Project structure

`HANDOFF.md` is the orientation document: current state, the two ideas
that explain the design, and the gotchas that have already caused bugs.


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
- `.github/workflows/publish.yml` — scheduled scrape and GitHub Pages deploy
- `NEXT_SEASON.md` — what needs changing when the 2026/27 fixtures go up

The web app adds no dependencies: the server is `http.server` from the standard
library, and the front end is plain JavaScript. Searching, filtering and the
selection maths all run in the browser over one payload, so a hosted copy needs
no back end at all.
