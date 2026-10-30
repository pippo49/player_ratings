"""Import match cards transcribed from the league's downloadable card images.

The league site cannot be scraped and its pages cannot always be saved, but
every match card has a "download image" button, and that image is a clean,
consistent rendering of the whole card. Reading one is reliable: the first
card tried this way reproduced the cached record exactly, all six players.

So the image is transcribed into JSON and imported here. The format mirrors
what the card shows rather than what the cache stores, so a transcription can
be checked against the picture line by line:

    [
      {
        "date": "2026-10-20",
        "division": 4,
        "season": "2026-27",
        "home": "Highbury 3",
        "away": "Irving 3",
        "score": "4-6",
        "singles": [
          ["Julian Warowioff", "Viktor Varga", "home"],
          ["Reuben Brown", "Tony Lee", "away"],
          ...
        ],
        "doubles": "away"
      }
    ]

Each singles entry is [home player, away player, who won]. "doubles" is who
took the doubles, or null if the card shows none.

Nothing is written unless --commit is passed, and nothing is written at all
if any check fails. The checks are the point: a transcription is only worth
having if a misreading is caught rather than quietly rated.

    python import_card.py cards.json            # check only
    python import_card.py cards.json --commit   # check, then write
"""
import argparse
import json
import sys
from datetime import date as Date
from pathlib import Path

from cache import load_matches, merge_matches, save_matches
from models import Match, PlayerResult, TeamResult
from player_identity import identity, normalise

SINGLES_PER_MATCH = 9


class Rejected(Exception):
    """A card that cannot be trusted. Never partially imported."""


def _side_players(card, side):
    """Each player on one side, in the order the card first lists them."""
    seen = []
    for home, away, _ in card["singles"]:
        name = home if side == "home" else away
        if name not in seen:
            seen.append(name)
    return seen


def _build(card, known: set[str]) -> Match:
    where = f"{card.get('home', '?')} v {card.get('away', '?')} on {card.get('date', '?')}"

    for field in ("date", "division", "season", "home", "away", "score", "singles"):
        if field not in card:
            raise Rejected(f"{where}: no {field!r}")

    singles = card["singles"]
    if len(singles) != SINGLES_PER_MATCH:
        raise Rejected(f"{where}: {len(singles)} singles listed, expected "
                       f"{SINGLES_PER_MATCH} — a line was missed or doubled")

    won = {"home": 0, "away": 0}
    tally: dict[str, list[int]] = {}
    for i, entry in enumerate(singles, 1):
        if len(entry) != 3:
            raise Rejected(f"{where}: singles line {i} is not "
                           f"[home player, away player, winner]")
        home_player, away_player, winner = entry
        if winner not in ("home", "away"):
            raise Rejected(f"{where}: singles line {i} has winner {winner!r}, "
                           f"expected 'home' or 'away'")
        won[winner] += 1
        for side, name in (("home", home_player), ("away", away_player)):
            rec = tally.setdefault((side, name), [0, 0])
            rec[1] += 1
            if winner == side:
                rec[0] += 1

    # The card prints its own result, so the transcription can be checked
    # against it rather than trusted. A misread winner shows up here.
    doubles = card.get("doubles")
    if doubles not in ("home", "away", None):
        raise Rejected(f"{where}: doubles is {doubles!r}, expected "
                       f"'home', 'away' or null")
    final = {"home": won["home"], "away": won["away"]}
    if doubles:
        final[doubles] += 1
    try:
        said_home, said_away = (int(x) for x in str(card["score"]).split("-"))
    except ValueError:
        raise Rejected(f"{where}: score {card['score']!r} is not like '4-6'")
    if (final["home"], final["away"]) != (said_home, said_away):
        raise Rejected(
            f"{where}: the card says {said_home}-{said_away}, but the lines "
            f"transcribed add up to {final['home']}-{final['away']} — "
            f"a winner or a line has been misread")

    # Three singles each is the normal shape; fewer means a short side, which
    # is legitimate but worth saying out loud rather than rating silently.
    for (side, name), (w, played) in sorted(tally.items()):
        if played != 3:
            print(f"  note: {name} ({side}) plays {played} singles, not 3")

    sides = {}
    for side in ("home", "away"):
        players = []
        for name in _side_players(card, side):
            w, _played = tally[(side, name)]
            # normalise(), not identity(): the scraper stores the plain
            # normalised name and the rating engine folds aliases in later.
            # Applying them here instead splits anyone who has one -- Henry
            # Adam went in under "henry adams" and sat apart from his own
            # earlier matches, showing 2 of 3 for the season rather than 2
            # of 6.
            players.append(PlayerResult(name=name,
                                        player_id=normalise(name),
                                        games_won=w))
        sides[side] = TeamResult(name=card[side], players=players,
                                 total_score=final[side])

    unknown = [p.name for side in sides.values() for p in side.players
               if identity(p.name) not in known]
    if unknown:
        raise Rejected(
            f"{where}: not seen before — " + ", ".join(sorted(unknown)) +
            "\n    A misread name invents a player rather than updating one. "
            "Check the spelling against the card; if it really is a new "
            "player, re-run with --allow-new.")

    return Match(division=int(card["division"]),
                 date=Date.fromisoformat(card["date"]),
                 season=card["season"],
                 match_id="",          # filled in against the cache below
                 home=sides["home"], away=sides["away"])


def _existing(cached, m: Match):
    """The same fixture already in the cache, however it got there.

    Keying on the league's match id alone is not enough: a card read from an
    image does not carry one, so a fixture already held as a stub would be
    added a second time rather than filled in.
    """
    for old in cached:
        if (old.season == m.season and old.date == m.date
                and normalise(old.home.name) == normalise(m.home.name)
                and normalise(old.away.name) == normalise(m.away.name)):
            return old
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cards", type=Path, help="JSON file of transcribed cards")
    ap.add_argument("--commit", action="store_true",
                    help="write to the cache; without it, only check")
    ap.add_argument("--allow-new", action="store_true",
                    help="accept player names not seen in any result before")
    args = ap.parse_args(argv)

    try:
        cards = json.loads(args.cards.read_text())
    except (OSError, json.JSONDecodeError) as e:
        print(f"Could not read {args.cards}: {e}")
        return 1
    if isinstance(cards, dict):
        cards = [cards]

    cached = load_matches() or []
    known = {identity(p.name) for m in cached
             for side in (m.home, m.away) for p in side.players}
    if args.allow_new:
        known = None

    built, failed = [], 0
    for card in cards:
        try:
            m = _build(card, known if known is not None else _AllKnown())
        except Rejected as e:
            print(f"REJECTED {e}")
            failed += 1
            continue

        old = _existing(cached, m)
        if old is not None:
            m.match_id = old.match_id or f"img-{m.date}-{identity(m.home.name)}"
            had = bool(old.home.players or old.away.players)
            state = "already held in full" if had else "held as a stub"
            print(f"  {m.date} Div {m.division} {m.home.name} v {m.away.name}"
                  f" — {state}, will be replaced")
        else:
            m.match_id = f"img-{m.date}-{identity(m.home.name)}"
            print(f"  {m.date} Div {m.division} {m.home.name} v {m.away.name}"
                  f" — new")
        for side in (m.home, m.away):
            for p in side.players:
                print(f"      {p.name:24s} won {p.games_won} of 3")
        built.append(m)

    if failed:
        print(f"\n{failed} card(s) rejected — nothing written. "
              f"Fix the transcription and re-run.")
        return 1
    if not built:
        print("\nNo cards to import.")
        return 1

    if not args.commit:
        print(f"\n{len(built)} card(s) check out. "
              f"Re-run with --commit to write them.")
        return 0

    # Replacing in place rather than through merge_matches, because a card
    # from an image may be filling in a fixture the cache holds under the
    # league's own id, which merge_matches would not recognise as the same.
    by_key = {(m.season, m.match_id): m for m in built}
    out, replaced = [], 0
    for old in cached:
        new = _existing(built, old)
        if new is not None:
            out.append(new)
            by_key.pop((new.season, new.match_id), None)
            replaced += 1
        else:
            out.append(old)
    out.extend(by_key.values())

    save_matches(out)
    print(f"\nWrote {len(out)} matches: {replaced} replaced, "
          f"{len(by_key)} added.")
    print("Run publish.py (or webapp.export) to rebuild the app payload.")
    return 0


class _AllKnown(set):
    def __contains__(self, item):  # --allow-new
        return True


if __name__ == "__main__":
    sys.exit(main())
