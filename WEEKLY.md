# The weekly update

About five minutes. Everything runs in WSL from
`~/python_projects/player_ratings`.

Results are saved by hand because Cloudflare challenges scripted requests to
tabletennis365 — from GitHub and from home alike. `import_saved.py` never
contacts the league; it only reads what the browser saved.

**Three pages, then one command.** One fixtures page and two ranking pages;
the command reads the folder and publishes.

```bash
uv run python import_saved.py /mnt/c/Users/ThroX/Downloads/tt365
```

Paths in full on purpose: a shell variable set in one terminal is gone in the
next, and an empty one used to read as "the current directory".

---

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
rebuild, and the choice is remembered. Which is better is still open: they
were a dead heat when measured and our calibration has since been corrected.
Saving match cards again (`--with-cards`) is what would settle it, since a
card saved later fills in a result already stored.

To bring records up to date as well, add `--with-cards` and it will list a
match card per result to save — about forty a week. Worth doing occasionally
rather than weekly; a card saved later fills in a result already stored,
without duplicating it.

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

## Useful flags

| | |
|---|---|
| `--dry-run` | Report what it found, write and push nothing |
| `--links` | Just print the fixtures page URL and stop |
| `--divisions 3,4,7` | Only import those divisions (currently importing all) |

## If the league ever answers requests again

`publish.py` fetches and publishes in one command, with no saving by hand.
Test it with `uv run python publish.py --dry-run`; if Cloudflare still
challenges, it says so and changes nothing.
