# The weekly update

Ten minutes, four steps. Everything runs in WSL from
`~/python_projects/player_ratings`.

Results are saved by hand because Cloudflare challenges scripted requests to
tabletennis365 — from GitHub and from home alike. `import_saved.py` never
contacts the league; it only reads what the browser saved.

---

## 1. Start clean

```bash
cd ~/python_projects/player_ratings && git pull
D=/mnt/c/Users/ThroX/Downloads/tt365
rm -rf "$D" && mkdir -p "$D"
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

## 3. Save the match cards

```bash
uv run python import_saved.py "$D" --open
```

It lists the cards it needs and writes them as clickable links to
`C:\Users\ThroX\Downloads\tt365\_cards_to_save.html`. Open that in Windows and
work down the list: click a link, let it load, then `Ctrl+S` → `Enter` →
`Ctrl+W`. Chrome remembers the folder and the **HTML Only** setting, so it is
three keystrokes each.

Expect 35–40 of them in a normal week.

## 4. Publish

```bash
uv run python import_saved.py "$D"
```

Merges the results, rebuilds the ratings, commits and pushes. The app updates
about a minute later: <https://pippo49.github.io/player_ratings/>

---

## When it says something unexpected

| It says | What happened |
|---|---|
| `... is empty` | Nothing saved into that folder yet |
| `saved as "Webpage, Single File"` | Wrong save option — re-save as HTML Only |
| `the page never finished writing` | Saved as "Complete" and the tab closed before it finished. Re-save as HTML Only |
| `saved while the browser check was still running` | Saved too early. Reload, wait for the results, save again |
| `Read 5 played fixture(s)` (too few) | The fixtures page only rendered one division. Click through each division before saving, or use the per-division links from `--links` |
| *N* results still need their card | Those few did not save. Save them and run step 4 again |
| `On branch X, not master` | `git checkout master`, then run step 4 again |

**You do not have to do it all in one sitting.** Save some, run step 4, save
more. It recalculates what is missing each time and publishes whatever it
has, so partial progress always counts.

## Useful flags

| | |
|---|---|
| `--dry-run` | Report what it found, write and push nothing |
| `--open` | Also open the link page in your browser |
| `--links` | Just print the fixtures page URL and stop |
| `--divisions 3,4,7` | Only import those divisions (currently importing all) |
