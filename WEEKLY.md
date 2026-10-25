# The weekly update

About ten minutes. Everything runs in WSL from
`~/python_projects/player_ratings`.

Results are saved by hand because Cloudflare challenges scripted requests to
tabletennis365 — from GitHub and from home alike. `import_saved.py` never
contacts the league; it only reads what the browser saved.

**It is one command, run two or three times.** Each run reads the folder,
publishes whatever it can, and tells you what is still missing.

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

## 3. Run it — it lists the match cards it needs

```bash
uv run python import_saved.py /mnt/c/Users/ThroX/Downloads/tt365
```

It writes the outstanding cards as clickable links and prints the path:

```
All 37 as clickable links: C:\Users\ThroX\Downloads\tt365\_cards_to_save.html
```

**Open that file in Windows yourself.** Nothing opens a browser for you —
launching one from WSL was tried and gave, in turn, `gio` errors, a single
tab, and Windows error dialogs.

Then for each link: click it, let it load, `Ctrl+S` → `Enter` → `Ctrl+W`.
Chrome remembers the folder and the **HTML Only** setting, so it is a click
and three keystrokes a card. Expect 35–40 in a normal week.

## 4. Run it again — this publishes

```bash
uv run python import_saved.py /mnt/c/Users/ThroX/Downloads/tt365
```

Same command. Merges the results, rebuilds the ratings, commits and pushes.
The app updates about a minute later:
<https://pippo49.github.io/player_ratings/>

If some cards did not save it publishes the rest and lists what is left —
save those and run it once more. **Partial progress always counts**, so you
can stop and come back.

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
