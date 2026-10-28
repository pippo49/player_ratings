# Handoff

State of the project as of 10 October 2026, written so a new session can pick
it up without replaying the conversation that built it. `README.md` covers how
to run things; this covers what is true and what to watch out for.

## Where things are

| | |
|---|---|
| `WEEKLY.md` | the weekly routine — three saved pages, one command |
| `MODEL.md` | the rating model as it stands, and the next steps on it |
| `README.md` | how to run everything |
| this file | what is true, and what has already gone wrong |

Tools worth knowing, all re-runnable:

| | |
|---|---|
| `import_saved.py` | reads saved pages, publishes — the weekly command |
| `compare_rankings.py` | ours against the league's, scored properly |
| `fit_scale.py` | refits `PREDICTION_SCALE`; run after any step change |
| `check_ladder.py` | whether the division ladder matches what call-ups do |
| `walkforward.py` | predicts each match of this season from only what came before it; the only test that can see a start-of-season rule |
| `diagnose.py` | what the league's pages hold, via the workflow |

## What this is

An ELO rating system for the Central London Table Tennis League, and a phone
app over it. The user is Philip Parsons, captain of **Apex 4** in Division 4.
He can call players up from **Apex 5** (Division 7), the club's only lower
side. A team match is 9 singles plus 1 doubles, so 10 points. He cares about
**points, not wins** — the target is a top-two finish for promotion.

Doubles are deliberately not modelled. He said so explicitly; `check_doubles.py`
only verifies the 9+1 format still holds.

## Current state

As of 28 October 2026.

| | |
|---|---|
| Matches | 1051 — 937 from 2025/26, 114 from 2026/27 (to 23 Oct) |
| Rated players | 843, of whom 653 also carry the league's own rating |
| Registered squads | 87 teams |
| Confirmed aliases | 19, plus 14 recorded non-matches |
| Scales | ours 285 points per 10:1 odds, the league's 960 |
| Payload | 393 KB |
| Live at | https://pippo49.github.io/player_ratings/ |

Division 4: St Katharines Trust 5 7.71, **Flick TTC 5 6.93 (the top-two
bar)**, Apex 4 ninth on 4.81 — a gap of **+2.12 points a match**. Promotion
is out of reach on current squads; the live question is the other end, where
safety sits at 4.66 and Apex 4 is 0.15 above it. Two played, both lost 1–9,
both against sides above them.

**Two sets of ratings are carried and either can be shown** — ours and the
league's, switched in the app, remembered per device. They were a dead heat
when measured (Brier 0.0964 theirs, 0.0980 ours), but that was before the
step-size fix below, and ours has not been re-measured against theirs since.
Doing that is the open question worth settling.

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

**Player ratings come from the league's own ranking, not from our engine.**
`import_saved.py` reads two saved ranking pages into
`data/tt365_ranking_<season>.json`, and `webapp/api.py` uses them when they
exist (`RATING_SOURCE=auto`). That is what makes the week three page saves
rather than forty: the match cards existed only to feed our engine.

The two are a dead heat on accuracy — Brier 0.0964 theirs against 0.0980
ours, with ours rated on last season alone so it was genuinely predicting,
against 0.1463 for ignoring ratings. There is no accuracy argument either
way; the effort is the whole argument.

What it costs: **per-player win/loss records stop moving**, since those come
from match cards. Results, the division table and projections stay current
from the fixtures page, which is stored as a result with a team score and no
line-up. `records_to` in the payload says how far the records reach and the
app shows it. `--with-cards` brings them back for a week's work. Our engine
is untouched and `RATING_SOURCE=elo` returns to it.

**Results now come from the user's own machine — a Raspberry Pi on his home
connection, on cron.** `publish.py` fetches, rebuilds the snapshot, commits
and pushes; the workflow deploys what arrives. Four runs a day, deliberately
modest: twelve a day from one address is what the GitHub schedule was doing
when Cloudflare started challenging it. The hosted app no longer offers a
fetch button, because the workflow it linked to can no longer fetch — it
shows the age of the data and the latest results instead.
The schedule was removed on 24 October 2026 because Cloudflare challenges
GitHub's runners (see the gotchas), so a scrape from there fetches nothing
however often it runs. `.github/workflows/publish.yml` still deploys on any
push to `master` touching `webapp/static/`, and still runs on demand for
squads, diagnostics and manual redeploys. **Step order matters** — see the
gotchas.

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

- `step = max(20, 160 / (1 + career/3))`, decaying with how much a player
  has ever played: **160** for a first-ever match, 53 by a seventh, 20 from
  about a twenty-first. See *How our rating is produced* in `MODEL.md`.
- Career means **career** team matches, carried across seasons. There is no
  start-of-season bump — that was tried and measured worse (below).

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

**Cloudflare challenges the scraper, and silence looked like success.**
Since 18 October 2026 every fixtures page answers `403` with
`server: cloudflare`, `cf-mitigated: challenge` and the "Just a moment..."
interstitial. It is a JavaScript challenge, not a block: nothing at the
league or the platform refused us, Cloudflare interposed before the request
reached the origin. `requests` does not execute JavaScript, so no
combination of headers can satisfy it — the challenge is "run this code".

The likely trigger is the three signals together: GitHub Actions runners are
Azure datacenter IPs (the cf-ray ends `-SJC`, a US edge hitting a London
league), the User-Agent says `ratings-bot`, and the schedule went from four
runs a day to twelve on 16 October, two days before it started.

**Do not drive a headless browser at it.** That is bot-check circumvention
rather than asking to be let in; the sandbox refuses it, and header rotation
would not have worked anyway. The routes are to ask the platform for a feed
or an allowlist (**parked — the user has the draft and does not want it
raised again; do not suggest it, append it to an answer, or close with it**),
to cut the request rate, or to run the scrape from a home
connection, whose profile is quite different.

`scrape_season` caught the 403 with an `except HTTPError` written for the
benign case — a season whose pages are not up yet 404s — so six days of
scheduled runs went green while the app quietly went stale. Losing every
division now raises `SeasonUnreachable`; all 404s still pass quietly, and one
season going dark no longer costs the other its results
(`test_scrape_failure.py`).

Diagnosing anything that only happens on the runner now goes through
`diagnose.py` and the workflow's `diagnose` input, which commits
`data/diagnosis.txt`. Job logs and build artifacts both come from blob
storage that the development sandbox is refused by policy, so a diagnostic
that prints is one nobody can read.

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

## How to judge a change to the ratings

Three separate mistakes this project has made came from measuring wrongly,
so the method matters as much as the idea:

1. **Rate on one season, predict the next.** Anything fitted on the matches
   it is scored against will flatter itself; `ours, all results` scores
   0.0716 against `ours, last season only` at 0.0980 for exactly that
   reason.
2. **Score with a Brier score**, never mean absolute error on wins. MAE pays
   for overconfidence and drove `PREDICTION_SCALE` to less than half its
   real value before anyone noticed.
3. **Look at the bucketed win rates too**, not just the summary number. They
   assume nothing, and they are what caught the error the summary hid.

Reference points on the current data: guessing 50-50 scores 0.1435, the
flat step scored 0.0987, the decaying step scores 0.0901.

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

## The rating model, and the three things that were wrong with it

### A seed is a guess, and must give way to evidence

The step size decays: 160 points for a player with no record, halving every
three team matches, floored at 20 (`elo.step_for`). It replaced a flat 48,
then 32, and it is the largest improvement measured here — Brier 0.0901
against 0.0987, where guessing 50-50 scores 0.1435.

The flat step let a seed stand as an assumption rather than a starting
guess. Molly Brown won one singles of eighteen and finished 94 points from
her seed, still in the league's top quarter, because no night could move her
more than about twenty points. She is now 313th of 843. Raising the flat
step does not fix this — at six times the old value she is still 380th and
predictions are much worse. Only a step that *falls* as a player's own
record grows does, which is also why settled ratings are now steadier than
before, not noisier.

Credit where due: the league's Bob proposed exactly this ("more thought into
how to best allocate starting ratings"), and the measurement agreed with him.

Changing the step changes how far apart the ratings sit, so
`PREDICTION_SCALE` must be refitted with it — it went 250 to 285. Run
`fit_scale.py` after any change to the step.

Three parameters fitted against 543 pairings of one season predicting the
next, so re-check with a second complete season. Every decaying shape tried
beat the flat one, which is not the shape of a fluke.

### A start-of-season bump makes it worse

A carried rating looks like a stale prior — a summer passes, players improve
or fall away — so returning players were given a step floor of 40 for their
first 6 matches of a season (`K_SEASON_SETTLE`, `K_SETTLE_FLOOR`). It was
documented as unmeasurable, because with one completed season a player's
career record *is* their season record and the floor never binds.

With 114 matches of 2026-27 it **is** measurable, by walking forward:
predict each match from only what came before it, which is what the system
does in use and the only test where career and season records differ. That
test is in `walkforward.py`.

| start-of-season floor | Brier |
|---|---|
| none (step stays at 20) | **0.0801** |
| 40 for 6 matches (what was in place) | 0.0805 |
| 60 for 6 | 0.0807 |
| 80 for 6 | 0.0810 |
| 120 for 6 | 0.0818 |
| 160 for 6 (full restart) | 0.0827 |

Every floor is worse than none, monotonically in its size. A paired
bootstrap over the same 300 pairings puts the penalty at +0.00032 (95%
interval +0.00011 to +0.00055) for the floor of 40 and +0.00257 for a full
restart, worse in 100% and 99% of resamples respectively. The floor was
removed; `step_for` now takes career alone.

The premise was wrong, not the arithmetic. A carried rating is *earned*
information and a summer destroys little of it — club standard is stable
enough year to year that last season's record predicts September better
than a fresh look does. Re-opening it discards evidence to chase a change
that mostly has not happened.

Caveats: 300 pairings is thin, and this is one season's opening. Re-check
with a second complete season. If a bump ever does earn its place it will
be small, because 160 was the worst option tested, not the best.

### Fitting a probability needs a proper scoring rule

The forecasting constant was briefly set to 120 by minimising mean absolute
error on wins out of three. MAE is not a proper scoring rule: if the true
chance is 0.7, predicting certainty scores 0.30 and predicting 0.7 scores
0.42, so it pays for overconfidence and the fit chased it. Reported error
fell; the probabilities got much worse — a 6/6 Division 7 player was given a
1% chance against a median Division 4 one.

Bucketing results by the rating gap that preceded them assumes nothing and
settles it: the observed win rates track **250** across the whole range, and
a Brier score agrees at 265. `fit_scale.py` now scores both ways and no
longer offers MAE. Maximum likelihood says 190, but it assumes a player's
three singles are independent — same player, same night — so it leans the
same way; prefer the buckets.

### The ladder and the scale must agree

`SCALE` (400) updates ratings; `PREDICTION_SCALE` (120) converts a rating gap
into a chance of winning. Splitting them fixed forecasts *within* a division —
scoreline error 1.76 to 1.17 — and broke them *between* divisions, because the
seed ladder is still 100 points per division.

Measured properly, the ladder is **about right and should be left alone**.
Sweeping the spacing from 100 down to 10, prediction error is best at 100 and
degrades all the way down; flattening it with a power curve halves the
far-gap bias for almost no cost but does not change the headline numbers.
Narrowing it, which looked obvious, would have wrecked the same-division and
one-apart cases that are 93% of the evidence.

What remains, at scale 250 and a 100-point ladder, is a residual bias that
grows with distance: same division and one apart sit within 0.02 of
unbiased; two apart is about 0.12; three apart about 0.22, on 13-19 pairings.
So the ladder is slightly too steep across large gaps and **cross-division
numbers stay the least trustworthy part of the model** — call-up projections
being where that bites. Measured call-ups win about 0.77 singles of 3
playing up, against a model that now says 0.3-0.5. `check_ladder.py` and the
by-gap breakdown re-measure both as results accumulate.

## Open items

- **Is our engine now better than the league's ranking?** They were level
  before the decaying step size went in, which improved ours by more than
  anything else measured. `compare_rankings.py` re-runs the comparison on a
  folder of saved pages and answers it. If ours wins clearly, the weekly
  routine needs match cards again — forty pages rather than three — and the
  allowlist request to the league stops being a convenience.
- **An unranked player sits at their division's median**, which is some real
  player's rating, so a stand-in and a measured number can look identical.
  The payload marks them (`ranked_tt365`) and the app shows a `~`. But the
  line-up optimiser still prefers an unknown player at the median over a
  measured weak one — 15 such players in Division 4. Seeding them at the
  division's lower quartile instead was proposed and not done; it is a guess
  about people we have no data on, so it was left to the user.
- **Apex 4 v Highbury 3, 6 October, cancelled by Highbury 3.** Under Rule
  43(b) the Divisional Secretary must hear the circumstances within 7 days or
  *neither* side gets the 3-point bonus. Two emails are drafted in the
  conversation but unsent — they need the time their notice arrived and the
  reason given. The user asked not to be reminded again.
- **Arturas Rybakas — settled, do not reopen.** 47/48 across two seasons,
  rated 1887 (31st of 843) and registered for St Katharines Trust 5 in
  Division 4, above everyone in that club's Division 1 and Division 2 sides.
  Worth about 1.1 points a match to that side on his own. A Rule 28(a)
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
  payload, which is already 393 KB.
- `MIN_MATCHES = 15` marks a rating "reliable" after 15 singles — only five
  team matches, arriving in correlated threes against the same opponents.
  Molly Brown and Umair Obaid both cleared it on records that plainly are
  not reliable. The information unit is the team match, not the singles.

## Working style the user expects

Short, concrete, honest. Report what the data says even when it is
unwelcome — he has twice corrected a too-optimistic framing and prefers the
blunt version. Flag bugs found along the way rather than quietly fixing them.
He confirms every identity decision himself and is happy to be asked, but
does not want repeated reminders about things he has parked.

Take that last point literally. Once he has said something is noted, it is
off the table — including as a closing line, a caveat, or "worth saying
plainly". Saying it a second time is a reminder; a third is nagging. This was
learned by doing it three answers running with the allowlist request.
