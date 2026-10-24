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
commits and deploys. Results are scraped every two hours from 07:23 to 23:23
UTC (23 minutes past, to miss the on-the-hour crush); the squad refresh is
the slow half — every team page — so it runs once a day at 06:47 UTC and is
skipped by the two-hourly schedule. Also runs on demand from the Actions tab.
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

**A short side is recorded two different ways.** Where the card fills the
empty slot with a placeholder, the opponents are credited with beating it, so
a walkover is already inside their win counts. Where the card simply lists
two players, it is not. The engine has to tell them apart before stripping
walkovers, or it under-credits a whole side by one win each — compare the
wins attributed against `len(home) x len(away)`, the singles that could
really be played. **Do not assume a card's singles sum to 9**: that only
holds when both sides field three.

**Short sides put `Forfeit` in the empty slot.** Taken literally it became a
rated player on two teams' rosters, and it made a short side look like a full
three so the walkover discount never fired. `parser_v2.NOT_A_PLAYER` filters
placeholders. Keep that pattern tight — a loose one deletes `Nabil Chair`,
`Natalia Ivanova` and `Noa Bye-Smith`.

**One number cannot explain itself.** The form badge is a rating change
over three team matches, and the window reaches back across the summer — a
player one match into the season is measured against two from last March. So
a sweep landing inside a bad run shows a red arrow, which was asked about
twice in a row before the fix. The player sheet now lists the three matches
behind the badge (`form_detail` in the payload, `formDetailBlock` in the
app), with the date span spelled out. `export.check()` asserts the rows sum
to the badge.

Worth keeping in mind for anything similar: a derived figure that surprises
someone is not usually wrong, it is unexplained, and the fix is to show its
inputs rather than to change the maths.

**A 3/3 can never lower a rating.** The change is `K x (actual - expected)`,
actual is 1.0 at a sweep and expected is always below it. Any apparent drop
after a sweep is the form window, not the engine.

**GitHub's scheduler drops runs.** It is best-effort, and demonstrably so:
of the first three six-hourly slots after the schedule was added, one ran 28
minutes late and two never fired at all. Hence two-hourly — the gap between
slots is the real staleness, not the nominal interval. Nothing in the repo
can fix this; the app just has to be honest about it, so the update sheet
says outright that a run was skipped once the snapshot is over four hours
old.

**`generated_at` is when a run last happened, not when the league last
changed.** Every export stamps it with the current time, so `ratings.json`
differs on every run and the commit always fires. That makes an old
timestamp a real signal that the scheduler is asleep — worth keeping.

**Added to the home screen, the app does not reload on reopening.** A
standalone PWA resumes the page it was showing, so a scrape that finished in
the background would never be seen. `app.js` re-checks `ratings.json` on
`visibilitychange` and `focus`, throttled to once every 30 seconds, and bails
on an unchanged `generated_at`. An open sheet is rebuilt with it — the update
sheet lists the latest results, so stale content there would mislead. The
service worker is network-first, so a reload still picks up new code.

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
- The form rows shown under the badge sum to the badge, and there are as
  many of them as it claims to span.
- Attributed singles on a card equal either 9, or `len(home) x len(away)`
  when a side is short — anything else means the card was misread.
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
- **Arturas Rybakas — settled, do not reopen.** 44/45 (98%) last season,
  rated 1827 and registered for St Katharines Trust 5 in Division 4, above
  everyone in that club's Division 1 and Division 2 sides. A Rule 28(a)
  rank-order query was drafted; it was never sent, and should not be. The
  league's "players restricted from playing up" list stars him, which *is*
  the declaration Rule 28(b) requires, so the registration is in order. The
  star locks him in the 5s: barred from playing up under 29(a), re-registrable
  higher only on application to the Committee, and not at all in the last six
  weeks. Nothing in the rules lets a higher-team player come down, so that
  side cannot be reinforced from above either. He is a fixture of Division 4
  for the season and the projections should be read with that as settled.
- **ASIA 1** registered for Division 4 but appears in nobody's fixtures; the
  division is 11 teams, not 12.
- **AA Academy** renamed from "AA Academy SJoA", so their squad fetches 404.
  They are playing, so results exist but squads do not.
- `season_transition.py` ROSTER_OVERRIDES is dead weight now real squads
  supersede it.
- The rating is a single current number. Per-season *records* are stored;
  per-season *ratings* and a full trend line are not. `PlayerRating.history`
  holds the whole trajectory in memory; only the last three matches are
  exported, as `form_detail`. Exporting all of it would roughly double the
  payload, which is already 332 KB.

## Working style the user expects

Short, concrete, honest. Report what the data says even when it is
unwelcome — he has twice corrected a too-optimistic framing and prefers the
blunt version. Flag bugs found along the way rather than quietly fixing them.
He confirms every identity decision himself and is happy to be asked, but
does not want repeated reminders about things he has parked.
