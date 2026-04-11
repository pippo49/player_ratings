"""Central League London ELO ratings — entry point."""

import argparse

from cache import load_matches, merge_matches, save_matches
from elo import calculate_ratings, lookup_player, lookup_team, top_players
from scraper import scrape_all_divisions


def _print_table(players, title: str) -> None:
    print(f"\n{'='*78}")
    print(f"  {title}")
    print(f"{'='*78}")
    print(f"{'Rank':<5} {'Name':<25} {'Team':<20} {'Div':>3} {'Rating':>7} {'M':>4} {'Win%':>6}")
    print(f"{'-'*78}")
    for rank, pr in enumerate(players, 1):
        win_pct = f"{pr.win_rate*100:.1f}%"
        reliable = "" if pr.reliable else "*"
        print(
            f"{rank:<5} {pr.name:<25} {pr.team:<20} {pr.division:>3} "
            f"{pr.rating:>7.1f} {pr.singles_played:>4} {win_pct:>6}{reliable}"
        )
    print("  M = singles matches played | * fewer than 15 singles matches")


def _load_or_scrape(args) -> list:
    """Load matches from cache, scrape, or update depending on flags."""
    if args.refresh:
        print("Full refresh — scraping all 7 divisions…\n")
        matches = scrape_all_divisions(verbose=True)
        save_matches(matches)
        return matches

    cached = load_matches()

    if args.update:
        print("Updating — scraping for new matches…\n")
        scraped = scrape_all_divisions(verbose=True)
        if cached:
            matches, added = merge_matches(cached, scraped)
            print(f"\n{added} new match(es) added.")
        else:
            matches = scraped
        save_matches(matches)
        return matches

    if cached:
        print(f"Loaded {len(cached)} matches from cache.")
        print("(use --update to check for new matches, --refresh for full re-download)\n")
        return cached

    # No cache yet — first run
    print("No cached data found — scraping all 7 divisions…\n")
    matches = scrape_all_divisions(verbose=True)
    save_matches(matches)
    return matches


def main() -> None:
    parser = argparse.ArgumentParser(description="Central League London ELO Ratings")
    parser.add_argument("search", nargs="*", help="Search for a player by name")
    parser.add_argument("--update", action="store_true", help="Scrape and add only new matches to the cache")
    parser.add_argument("--refresh", action="store_true", help="Full re-download of all matches (replaces cache)")
    parser.add_argument("--division", "-d", type=int, choices=range(1, 8), help="Show full table for a division (1-7)")
    parser.add_argument("--team", "-t", type=str, help="Search for a team by name")
    args = parser.parse_args()

    print("Central League London ELO Ratings — Winter 2025/26\n")

    matches = _load_or_scrape(args)
    total_players = len({
        p.player_id
        for m in matches
        for p in m.home.players + m.away.players
    })
    print(f"Total matches: {len(matches)} | Unique players: {total_players}")
    print("Calculating ELO ratings (iterative)…")

    ratings = calculate_ratings(matches)

    # Specific lookups — show only what was asked for
    if args.division:
        players = top_players(ratings, division=args.division, n=100, min_matches=0)
        _print_table(players, f"Division {args.division} — All Players")
        return

    if args.team:
        results = lookup_team(ratings, args.team)
        if results:
            _print_table(results, f"Team: '{args.team}'")
        else:
            print(f"\nNo players found for team '{args.team}'.")
        return

    if args.search:
        query = " ".join(args.search)
        results = lookup_player(ratings, query)
        if results:
            _print_table(results, f"Search: '{query}'")
        else:
            print(f"\nNo players found matching '{query}'.")
        return

    # Default: full league tables
    _print_table(top_players(ratings, n=20), "Overall Top 20 (min 15 singles)")

    for div in range(1, 8):
        players = top_players(ratings, division=div, n=10)
        if players:
            _print_table(players, f"Division {div} — Top 10")


if __name__ == "__main__":
    main()
