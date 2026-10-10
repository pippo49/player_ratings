# Handoff

State of the project as of 10 October 2026, written so a new session can pick
it up without replaying the conversation that built it. `README.md` covers how
to run things; this covers what is true and what to watch out for.

## What this is

An ELO rating system for the Central London Table Tennis League, and a phone
app over it. The user is Philip Parsons, captain of **Apex 4** in Division 4.
He can call players up from **Apex 5** (Division 7), the club's only lower
side. A team match is 9 singles plus 1 doubles, so 10 points. He cares about
**points, not wins** — the target is a top-two finish for promotion.

Doubles are deliberately not modelled. He said so explicitly; `check_doubles.py`
only verifies the 9+1 format still holds.

## Current state

| | |
|---|---|
| Matches | 961 — 937 from 2025/26, 24 from 2026/27 |
| Rated players | 828 |
| Registered squads | 615 players across 87 of 94 teams |
| Confirmed aliases | 19, plus 14 recorded non-matches |
| Live at | https://pippo49.github.io/player_ratings/ |

Division 4 projection: St Katharines Trust 5 6.83, **Flick TTC 5 6.08 (the
top-two bar)**, Apex 4 eighth on 4.64 — a gap of **+1.44 points per match**.
On current squads, promotion is a stretch rather than a near miss. Apex 3
(Division 3, 5.11 against a 5.57 bar) is the better prospect, and opened 10–0.

## How it fits together

```
tabletennis365.com
   │  fetch_structure.py   → data/teams_2026-27.json     (team → division)
   │  fetch_squads.py      → data/squads_2026-27.json    (team → players)
   │  scraper.py/main.py   → data/matches.json           (results)
   ↓
elo.py            ratings from matches
webapp/api.py     payload: ratings + squads + divisions
webapp/export.py  → webapp/static/ratings.json
GitHub Pages      static app, offline-capable
```

Everything runs through `.github/workflows/publish.yml`, which scrapes,
commits and deploys. It runs weekly (Mondays 07:00 UTC) and on demand.
**Step order matters** — see the gotchas.

The development sandbox cannot reach tabletennis365.com. Anything needing the
league site runs as a workflow dispatch and is read back from the job log.
Diagnostic inputs (`report_fixtures`, `fetch_pages`, `validate_parser`,
`fetch_squads`, `fetch_structure`) skip the commit and deploy steps.

## The two ideas that explain most of the code

### 1. The name is the identity

The league reissues numeric player ids every season — of 121 returning
players, **none** kept their id. So ids identify an appearance, not a person,
and the 2026/27 match cards carry no id at all.

`player_identity.identity()` is the single answer to "who is this": normalise
the name, then resolve any confirmed alias. **Everything that keys on a player
must go through it** — `elo.canonical_ids`, the squad loader, the per-season
records. Three separate bugs came from `normalise()` being used as an identity
in places that then disagreed with each other.

Anything short of an exact match is confirmed by a human before it lands in
`data/player_aliases.json`. The matcher offers candidates three ways:
exact spelling (≥0.80 similarity), **surname-plus-initials** (`Cp Sahu` =
`Chandra Prakash Sahu`, which scores 0.52 and would never surface otherwise),
and **same club** at a lower floor of 0.62. Rejections are recorded too, or
the same false positive returns every week; `not_matches` takes a list,
because Fusion have three Dennisons.

### 2. Each season is converged on its own, seeded from the last

Last season's matches are **never replayed**. They are compressed into one
number — the rating a player starts the new season on. Within a season the
engine replays everything to a fixed point, so **order carries no weight**
(verified: reversing the fixture order moves ratings by 0.000).

K-factor is the step size — how far one team match can move you:

- **48** while provisional, **32** once established
- Provisional means fewer than 15 **career** team matches, *or* fewer than
  **6 this season** (`K_SEASON_SETTLE`). A carried rating is a stale prior —
  a summer passes — so everyone starts a season provisional again.
- Sweeping 3/3 against equals moves a provisional player ~22 points, an
  established one ~15.

Seeds come from the division ladder (`SEASON_SEEDS`), per season because the
league restructured for 2026/27 by adding a Premier tier. A player's seed uses
the division of the team they **registered** with, not the one they appear in
— a call-up plays in the borrowing team's division, which is not their level.

## Gotchas that have already bitten

Each of these was a live bug. They are the things most likely to recur.

**The team page changes meaning once a team plays.** Before: the registered
squad, complete and authoritative. After: a results view that drops squad
members who have not turned out *and* lists the opposition's players. So
`fetch_squads.py` merges rather than overwrites for teams that have played,
taking their squad from what was recorded plus the match cards.

**Therefore the workflow must scrape results before refreshing squads.** That
test ("has this team played?") reads the cached results. With the old order it
read last week's cache and the squad overwrite happened anyway.

**A call-up is not a squad member.** A player who turns out for another side
of their own club is not added to its squad — that is how Apex 4 borrows from
Apex 5, and it is common.

**Short sides put `Forfeit` in the empty slot.** Taken literally it became a
rated player on two teams' rosters, and it made a short side look like a full
three so the walkover discount never fired. `parser_v2.NOT_A_PLAYER` filters
placeholders. Keep that pattern tight — a loose one deletes `Nabil Chair`,
`Natalia Ivanova` and `Noa Bye-Smith`.

**Fixture dates carry no year** ("Fri 06 Nov"). The year comes from the
season: August onwards is the first calendar year, January onwards the second.

**A played fixture's team cell contains the line-up**, so the team name must
come from the team link, not the cell text.

**Registered squads apply all season**, not just before the first result.
Results say how good a player is, not whether they are still in the side. The
hand-maintained bridge in `season_transition.py` *does* stand down once real
results exist — that part is guesswork and should.

**Divisions come from the published structure**, not from results. Results can
only tell you which division a team played in *last* season.

**Junior sides host nearly every fixture.** Fusion 8 Jr and Morpeth 11 Jr play
19 of 20 at home, so Apex 4 travel for both legs against each and the home/away
split is 8/12, not 10/10. This is real scheduling, not a parse error.

## Invariants worth asserting

These catch whole classes of error, and did:

- Every player's per-season records sum to their career totals.
- No duplicate rows per normalised name (except `jolanta gotovska`, two
  different players sharing a name in 2025/26, deliberately kept apart).
- `validate_parser.py` re-parses finished 2025/26 matches and diffs them
  against the known-good cache — currently 10 of 10 identical.
- Reversing a season's fixture order must not change any rating.
- A rating change must only ever touch players who played in the season
  being changed.

## Open items

- **Apex 4 v Highbury 3, 6 October, cancelled by Highbury 3.** Under Rule
  43(b) the Divisional Secretary must hear the circumstances within 7 days or
  *neither* side gets the 3-point bonus. Two emails are drafted in the
  conversation but unsent — they need the time their notice arrived and the
  reason given. The user asked not to be reminded again.
- **Arturas Rybakas**, 44/45 (98%) last season, is registered for St Katharines
  Trust 5 in Division 4 — stronger than every player in that club's Division 1
  and Division 2 sides. Rule 28(a) rank-order query drafted, not sent. His
  club has not played yet, so the registration page is still authoritative.
- **ASIA 1** registered for Division 4 but appears in nobody's fixtures; the
  division is 11 teams, not 12.
- **AA Academy** renamed from "AA Academy SJoA", so their squad fetches 404.
  They are playing, so results exist but squads do not.
- `season_transition.py` ROSTER_OVERRIDES is dead weight now real squads
  supersede it.
- The rating is a single current number. Per-season *records* are stored;
  per-season *ratings* and a trend line are not. `PlayerRating.trail` holds
  the trajectory in memory but is not exported.

## Working style the user expects

Short, concrete, honest. Report what the data says even when it is
unwelcome — he has twice corrected a too-optimistic framing and prefers the
blunt version. Flag bugs found along the way rather than quietly fixing them.
He confirms every identity decision himself and is happy to be asked, but
does not want repeated reminders about things he has parked.
