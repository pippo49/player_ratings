# The rating model, as it stands

28 October 2026. What the numbers in the app actually are, how they are
produced, and what is known to be wrong with them.

`HANDOFF.md` covers the project as a whole and the traps in the league's
data. This file is the model alone.

---

## Two sets of ratings

The app carries both and switches between them in the header.

| | ours | the league's |
|---|---|---|
| Source | computed here from match cards | TT365's published ranking |
| Range | 956–2113 | 0–3285 |
| 10:1 odds | **285 points** | **960 points** |
| Updates | whenever cards are imported | republished monthly |
| Coverage | all 843 players | 653; the rest get a stand-in |
| Needs | ~40 saved pages a week | 2 saved pages a week |

They were a **dead heat** when first measured — Brier 0.0964 theirs against
0.0980 ours. **That is no longer so.** Re-measured after the step size
changed, with ours rated on 2025-26 alone and both asked about 2026-27:
**ours 0.0850, theirs 0.1023**, over the 700 pairings where 534 players
carry both ratings, against 0.1413 for guessing. Paired, ours is ahead in
100% of 4000 resamples.

The comparison is tilted their way — their published numbers already include
the matches being scored and ours do not — so the gap understates us.
`check_vs_league.py` re-runs it from the cache without saved pages.

The practical upshot: the ~40 cards a week buy real accuracy over the
2-page route, so the effort is not merely a preference.

A player the league does not rank is shown at their division's median,
marked `~` in the app and `ranked_tt365: false` in the payload. That median
is a real player's rating, so without the mark the two are indistinguishable.

---

## How our rating is produced

### 1. A player starts at their division's level

`SEASON_2026_27_SEED`: Premier 1850 down to Division 7 1150, 100 apart.

The seed says what a player's club thinks of them, not what they can do.
Sweeping the spacing from 100 down to 10 showed 100 predicts best and every
narrower ladder is worse, so it stands — but it has only ever been tested
where players meet their own division, which is nearly always.

### 2. Each match moves them

> new rating = old + **step** × (singles won − singles expected)

Expected comes from the rating gap, using `PREDICTION_SCALE`.

### 3. The step shrinks as a record accumulates

```
step = max(20, 160 / (1 + career_team_matches / 3))
```

| their match | step |
|---|---|
| 1st | 160 |
| 4th | 80 |
| 7th | 53 |
| 13th | 32 |
| 21st+ | 20 |

The step bounds a move rather than being it. A match moves a player by
`step × (share of singles won − share expected)`, so a first-timer sweeping
3-0 against equals gains 80, not 160; the full 160 needs a result nobody
expected at all. For an even match the realistic swing is about ±80 at the
start and ±10 once settled.

Note the curve is harmonic, not exponential: the step halves after 3 team
matches, again at 9, and again at 21. It is not "halving every three", and
reading it that way overstates how quickly a player stops moving.

A newcomer's own results overwhelm the seed within a handful of matches;
once they have a record the step is *below* the flat 32 it replaced, so
settled ratings are steadier than before, not noisier.

There is **no start-of-season bump**. Returning players once got a floor of
40 for their first 6 matches, on the grounds that a summer passes and a
carried rating is a stale prior. Measuring it reversed the decision.

Walking forward through 2026-27 — predicting each match from only what came
before it, the one test where a player's career and season records differ —
every floor tried came out worse than none, in proportion to its size: 40
cost 0.00032 Brier, a full restart at 160 cost 0.00257, worse in 100% and
99% of paired bootstrap resamples. A carried rating turns out to be *earned*
information that a summer destroys little of; re-opening it discards
evidence to chase a change that mostly has not happened. `walkforward.py`
runs the test; `HANDOFF.md` has the full table and caveats.

### 4. The season is replayed until it settles

Every match is re-run up to 20 times until no rating moves more than 0.5.
Order therefore carries no weight: reversing the fixture list moves ratings
by 0.000. Seasons are converged separately, each seeded from the last one's
close; last season's matches are never replayed.

### 5. Reading a rating as a probability

```
chance of winning = 1 / (1 + 10 ^ (gap / 285))
```

**285, not Elo's textbook 400.** 400 made every forecast sit too close to
even and flattened team projections toward 5–5. Fitted by grouping results
by the rating gap that preceded them and counting how often the stronger
player won.

**This constant must be refitted whenever the step changes** — a different
step spreads the ratings differently and this number describes that spread.
It was 250 under the flat step. Run `fit_scale.py`.

Note `SCALE = 400` is still used *inside* the update. That is deliberate and
tested: rating with a steeper constant makes a favourite's win worth nothing
and an upset worth everything, and predictions get worse.

### 6. Team projections

Every side on the three its appearances say it fields, against the same for
each opponent, averaged over the division. Assuming a side plays its best
three overstates it by about 72 rating points, so doing that for the side
being projected while its opponents rotated overstated every team in the
league by a full match point (+1.01 mean error across the 91 sides with four
or more matches played; scoring both ends alike leaves +0.03, and cuts mean
absolute error from 1.15 to 0.78).

A captain's own card is the one exception, and only for call-ups. A player
from a lower club side is not part of the attendance record being weighted,
and is rung when the side is short of bodies rather than to improve on a
regular who is free to play. So a call-up takes no place while three of the
side's own are available; they fill only the places nobody else can, drawn
from their own side's attendance in turn.

The doubles is the tenth point and is taken from the gap between the two
trios' mean ratings, at `DOUBLES_SCALE = 240`. Who paired up is never
recorded, so it cannot be predicted from names — but the stronger trio takes
it 71% of the time, and the even split this used to assume was flattening the
projected table at both ends: modelling it moves the slope of actual on
projected from 1.61 to 1.38, where 1.00 would be right.

The remaining compression is in the singles curve, and is not yet fixed. It
runs the same way in all eight divisions, from 1.16 in Division 1 to 2.32 in
Division 7 after the doubles is allowed for, so lower divisions are squashed
hardest — consistent with the seed anchoring holding players near their
division's median. Steepening `PREDICTION_SCALE` from 340 to about 200 closes
it, and walk-forward Brier mildly prefers 240 over 340, but that rests on 232
predictions and the rest of the evidence is in-sample. Do not move it on
these numbers alone; refit properly with `walkforward.py` and `fit_scale.py`,
and treat the upward drift of that constant as part of the same question.

---

## The step schedule is slightly too tight

Measured 27 November 2026 by `walkforward_implied.py` and
`walkforward_step.py`, which walk **both** seasons in date order and score
21,850 pairings out of sample. `walkforward.py` walks the current season only,
because that is the only way to see a start-of-season rule; these two walk
everything, because the question is about the step curve rather than the
season boundary.

A player's own record holds information the engine has not taken. Predicting
them at `model + blend x (implied - model)`, where `implied` is solved from
every singles result so far against the ratings their opponents held at the
time, beats the engine for blends up to about a quarter:

| blend | Brier | vs engine | 95% paired |
|---|---|---|---|
| engine | 0.0935 | | |
| 0.15 | 0.0932 | -0.00034 | -0.00048 to -0.00021 |
| 0.25 | 0.0933 | -0.00022 | -0.00045 to -0.00001 |
| 0.35 | 0.0936 | +0.00011 | crosses zero |
| 1.00 | 0.0989 | +0.00535 | +0.00465 to +0.00612 |

A single mid-season split had suggested 0.25 was worth -0.0015, seven times
what both seasons give. One split of one season overstates things; this is
why the walk exists.

The same gain is available inside the engine, which is the better shape for
it, since a prediction-time blend leaves every other reader of a rating on the
old number:

| change | Brier | vs engine | 95% paired |
|---|---|---|---|
| `K_HALF_LIFE` 3 -> 4 | 0.0932 | -0.00031 | -0.00040 to -0.00021 |
| `K_HALF_LIFE` 3 -> 6 | 0.0932 | -0.00026 | -0.00048 to -0.00004 |
| `K_FLOOR` 20 -> 40 | 0.0934 | -0.00006 | -0.00011 to -0.00001 |
| `K_HALF_LIFE` 3 -> 9 | 0.0937 | +0.00015 | crosses zero |
| `K_START` 160 -> 120 | 0.0953 | +0.00184 | +0.00160 to +0.00208 |

**Not applied.** The gain is real and clear of zero, but it is the same order
as moving `PREDICTION_SCALE` from 320 to 340, which the comment in `elo.py`
calls worth very little on its own. Changing `K_HALF_LIFE` moves every rating
in the app and forces a refit of `PREDICTION_SCALE` and the squad-shortfall
constants, all of which are rating-point quantities keyed to the step. That is
a lot of movement for 0.0003, and it should be taken as one deliberate change
with the refits done alongside, not slipped in.

It also does not fix the case that prompted the measurement. Ziye Ke's record
implied a rating 318 points above his own; his step budget over four nights
goes from 155 to 191 at `K_HALF_LIFE = 4`. Still nowhere near. A player whose
rating and record plainly disagree needs something keyed to that disagreement,
not a uniformly looser step -- and 23% of the league is in that position, worst
in Divisions 1 and 2 at 30% and 32%, where careers are longest.

---

## What is known to be wrong

**Cross-division comparisons.** Bias is near zero for players one division
apart and grows with distance: about 0.12 at two divisions, 0.22 at three,
on 13–19 pairings. **Call-up projections are the least trustworthy number in
the app.** Measured call-ups win about 0.77 singles of 3 playing up; the
model says 0.3–0.5.

**Unknown players outrank measured weak ones.** On the league view a player
they do not rank sits at the division median — above every genuinely
below-average player. 15 such players in Division 4, and the line-up
optimiser will pick them. Seeding them at the lower quartile was proposed
and not done: it is a guess about people we have no data on.

**`MIN_MATCHES = 15` is too low.** It marks a rating reliable after 15
singles — five team matches, arriving in correlated threes against the same
opponents. The information unit is the team match, not the singles.

**Three parameters fitted on one season predicting the next**, across 543
pairings. Every decaying shape beat the flat one, which is not the shape of
a fluke, but a clean test needs data nobody has looked at yet.

---

## Next steps, in order

The first two items are now answered and kept here as the reason for the
third.

1. ~~Re-measure ours against the league's ranking.~~ **Done.** Ours wins
   clearly out of sample — 0.0850 against 0.1023, ahead in 100% of paired
   resamples. `check_vs_league.py` re-runs it from the cache any week.
2. ~~Decide the weekly routine on that result.~~ **Match cards win.** The
   three-page route would cost real accuracy, so importing cards is worth
   the effort rather than a preference.
3. **Keep the cards coming.** Whatever makes that sustainable is the most
   valuable thing to improve, because everything in the model depends on
   results arriving. A division's own cards are what keep its players
   current, so a partial week — one division rather than all eight — is
   worth far more than nothing.
4. **Decide on unranked players** — leave them at the median and read past
   the `~`, or drop them to the lower quartile so unknowns stop outranking
   known-weak players.
5. **Raise `MIN_MATCHES`**, or express it in team matches.
6. **Re-fit with a second complete season**, when there is one.
   `fit_scale.py` for the scale, the variants sweep for the step, and
   `walkforward.py` for anything conditioned on the start of a season.
   All are re-runnable.
7. **Re-measure the ladder** once more call-ups accumulate
   (`check_ladder.py`). 39 pairings cannot settle it; a season might.

---

## How to judge any change to this

Three separate mistakes here came from measuring wrongly, so:

- **Rate on one season, predict the next.** Anything scored on the matches
  it was fitted to will flatter itself — 0.0716 against 0.0980 for exactly
  that reason.
- **Score with a Brier score, never mean absolute error on wins.** MAE pays
  for overconfidence; it drove `PREDICTION_SCALE` to less than half its real
  value while reporting an improvement.
- **Read the bucketed win rates, not just the summary.** They assume nothing,
  and they caught the error the summary hid.

Reference points on current data: guessing 50-50 scores **0.1435**, the flat
step scored **0.0987**, the decaying step scores **0.0901**.
