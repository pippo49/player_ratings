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

They were a **dead heat** when last measured — Brier 0.0964 theirs against
0.0980 ours, where guessing 50-50 scores 0.1435. **That was before the step
size changed**, which improved ours to 0.0901 against a comparable baseline.
Re-measuring is the first item under Next steps.

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

Each side's strongest three against the three each opponent usually fields,
averaged over the division. The fielded trio is estimated by appearance
weighting, since assuming everyone plays their best three overstates them by
about 72 rating points. Converted to match points assuming an even split on
the doubles, which is not modelled — the data does not say who paired up.

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

1. **Re-run `compare_rankings.py` on a folder of saved pages.** Ours against
   the league's, now that the step size has changed. This decides everything
   below it.
2. **If ours wins clearly:** the weekly routine needs match cards again —
   about forty pages rather than three — so the allowlist request to the
   league stops being a convenience and becomes the thing that makes it
   viable. If it is still a tie, stay on the league's ratings and three
   pages.
3. **Re-fit with a second complete season**, when there is one. `fit_scale.py`
   for the scale, the variants sweep for the step. Both are re-runnable.
4. **Decide on unranked players** — leave them at the median and read past
   the `~`, or drop them to the lower quartile so unknowns stop outranking
   known-weak players.
5. **Raise `MIN_MATCHES`**, or express it in team matches.
6. **Re-measure the ladder** once more call-ups accumulate
   (`check_ladder.py`). 15 cases cannot settle it; a season might.

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
