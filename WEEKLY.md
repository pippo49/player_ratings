# The weekly update

Run it in **WSL**, not on the Pi: the browser saves into Windows Downloads
and WSL reads that same disk at `/mnt/c/...`, so nothing has to be copied.

Results are saved by hand because Cloudflare challenges scripted requests to
tabletennis365 — from GitHub, from this sandbox and from home alike, so it
is not about where the request comes from. `import_saved.py` never contacts
the league; it only reads what the browser saved.

Paths in full on purpose: a shell variable set in one terminal is gone in the
next, and an empty one used to read as "the current directory".

---

## The whole routine

```bash
# 1. fetch
cd ~/python_projects/player_ratings && git pull
rm -rf /mnt/c/Users/ThroX/Downloads/tt365
mkdir -p /mnt/c/Users/ThroX/Downloads/tt365
```

**2. Save three pages** into that folder, as **Webpage, HTML Only**:

```
https://www.tabletennis365.com/CentralLondon/Fixtures?leagueName=Winter%202026-27
https://www.tabletennis365.com/CentralLondon/Ranking
https://www.tabletennis365.com/CentralLondon/Ranking?p=2
```

```bash
# 3. update — publishes straight away
uv run python import_saved.py /mnt/c/Users/ThroX/Downloads/tt365
```

Every result, the division table and the league's own ratings are now
current. Takes about two minutes.

```bash
# 4. find the match cards still wanted
uv run python import_saved.py /mnt/c/Users/ThroX/Downloads/tt365 --with-cards
```

This lists each result still missing its line-up and writes a page of
clickable links, telling you where it landed. Work down it: click, let it
load, **Ctrl+S**, Enter, **Ctrl+W** — about four seconds each.

```bash
# 5. import the cards — publishes again
uv run python import_saved.py /mnt/c/Users/ThroX/Downloads/tt365 --with-cards
```

Expect it to say **N line-up(s) filled in**. A result already held as a stub
stays on the missing-cards list until its card arrives, so nothing is lost
by doing step 5 days later, or a division at a time.

**Too many cards?** Add `--divisions 4,7`. The rest keep their correct team
scores as stubs and stay on the list for later.

---

## Results the league has not published yet

Your own match often is not on the site for days. Nothing above can pick
those up, so send Claude the **card image** (the download button on a match
card) or a **photo of the paper result sheet**, and it goes in through
`import_card.py`.

A paper sheet is the better of the two: the captains write a per-player set
count in the header, which checks the reading of the grid independently.

Reading an image is not as safe as saving the page. A rotated or shadowed
photo has had two players' results swapped, and none of the checks caught
it — the team total still added up and both names were real. Prefer saved
HTML whenever the result is actually on the site.

---

# In more detail

## 1. Start clean

```bash
cd ~/python_projects/player_ratings && git pull
rm -rf /mnt/c/Users/ThroX/Downloads/tt365
mkdir -p /mnt/c/Users/ThroX/Downloads/tt365
```

## 2. Save the fixtures page — one page, every division

<https://www.tabletennis365.com/CentralLondon/Fixtures?leagueName=Winter%202026-27>

Wait for the results to appear on screen, then `Ctrl+S` into
`C:\Users\ThroX\Downloads\tt365`.

Save as **Webpage, HTML Only**.

Not "Complete" — it keeps downloading in the background, and closing the tab
cancels it, leaving a `_files` folder and no page. Not "Single File" — that
writes `.mhtml`, which cannot be read. HTML Only writes one file instantly
from what is on screen, which is all the importer needs.

## 3. Save the ranking — two pages

<https://www.tabletennis365.com/CentralLondon/Ranking>
<https://www.tabletennis365.com/CentralLondon/Ranking?p=2>

Same again: wait for the table, `Ctrl+S`, **Webpage, HTML Only**. Check for a
`?p=3` — save it too if there is one. These carry a rating for every active
player, which is what replaces the forty match cards.

## 4. Run it — this publishes

```bash
uv run python import_saved.py /mnt/c/Users/ThroX/Downloads/tt365
```

Merges the results, takes player ratings from the ranking, rebuilds, commits
and pushes. The app updates about a minute later:
<https://pippo49.github.io/player_ratings/>

### What this does and does not keep current

| | |
|---|---|
| Player ratings, form | the league's ranking — current |
| Results, division table, projections | the fixtures page — current |
| Per-player win/loss records | **frozen** — they need match cards |

The app says so: the header reads "league ratings", and a player's sheet
notes the date their record runs to.

**Both sets of ratings are kept.** The payload carries ours and the league's,
and a **Mine / League** switch under the header moves between them — no
rebuild, and the choice is remembered. Which is better is **settled**: ours predicts
better, 0.0851 against 0.1028 on 1426 pairings, ahead in 100% of paired
resamples — and that is a floor, since their numbers have already seen the
matches being scored and ours have not. `check_vs_league.py` re-runs it from
the cache.

Because ours predicts better, the match cards earn their keep: skipping
them means running on the weaker of the two sets of ratings. About forty a
week, which is roughly ten minutes with the links page.

---

## When it says something unexpected

| It says | What happened |
|---|---|
| `No folder given` | The path was empty — pass it in full |
| `... is empty` | Nothing saved into that folder yet |
| `saved as "Webpage, Single File"` | Wrong save option — re-save as HTML Only |
| `the page never finished writing` | Saved as "Complete" and the tab closed before it finished. Re-save as HTML Only |
| `saved while the browser check was still running` | Saved too early. Reload, wait for the results, save again |
| `Read 5 played fixture(s)` (far too few) | The fixtures page rendered one division only. Click through each before saving, or use the per-division links from `--links` |
| `ignored cache.py`, `ignored README.md` … | It is reading the repo, not your saves — the path was wrong |
| `Nothing new on those pages` | Everything on them is already published |
| `On branch X, not master` | `git checkout master`, then run it again |
| `No new results to add` after saving cards | Was a bug: cards filling in stubs were discarded. Fixed — `git pull` and re-run |

## Useful flags

| | |
|---|---|
| `--dry-run` | Report what it found, write and push nothing |
| `--links` | Just print the fixtures page URL and stop |
| `--divisions 3,4,7` | Only import those divisions; the rest stay as stubs |
| `--with-cards` | Expect a card per result: lists the ones still wanted and writes the links page |

## Checking the model after a big import

More results means the thin measurements can be re-run. None of these
contact the league; they all read the cache.

| | |
|---|---|
| `check_vs_league.py` | ours against the league's ranking |
| `fit_scale.py` | refits `PREDICTION_SCALE` |
| `walkforward.py` | anything conditioned on the start of a season |
| `check_drift.py`, `check_drift_oos.py` | whether playing up is rated correctly |
| `check_ladder.py` | whether the division ladder matches what call-ups do |

## If the league ever answers requests again

`publish.py` fetches and publishes in one command, with no saving by hand.
Test it with `uv run python publish.py --dry-run`; if Cloudflare still
challenges, it says so and changes nothing.
