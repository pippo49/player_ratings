"""Compare ELO ratings with Warne Cup 2026 handicap ratings from PDF."""

import re
import sys
from pathlib import Path
from typing import NamedTuple

import pymupdf

from cache import load_matches
from elo import calculate_ratings

PROJECT_DIR = Path(__file__).resolve().parent
PDF_PATH = PROJECT_DIR / "Warne cup Player ratings 2026 Rev.A.pdf"
OUTPUT_PATH = PROJECT_DIR / "analysis_results" / "warne_cup_2026.txt"


class EloEntry(NamedTuple):
    name: str
    rating: float
    division: int
    win_rate: float
    singles_played: int


class Result(NamedTuple):
    name: str           # name as it appears in the PDF
    handicap: int
    team: str
    elo: float
    expected: float     # expected ELO from the linear fit
    diff: float         # elo - expected
    division: int
    win_rate: float
    singles_played: int

# Column x-boundaries: (min_x, max_x) for each of the 5 columns
COL_BOUNDS = [(0, 143), (143, 250), (250, 350), (350, 450), (450, 600)]

# Known team name prefixes for detecting header rows
TEAM_PREFIXES = [
    "Highbury", "Apex", "Clissold", "Irving", "Walworth",
    "St Katharine", "Flick", "Exiles", "Morpeth", "TJ TTC",
]

# Skip rows containing these strings
SKIP_PATTERNS = [
    "Non-playing", "CENTRAL", "LONDON", "TABLE", "TENNIS", "LEAGUE",
    "Warne", "Sheet", "Page", "Revision",
]


def _assign_column(x: float) -> int:
    """Return column index (0-4) for a given x-coordinate, or -1 if outside."""
    for i, (lo, hi) in enumerate(COL_BOUNDS):
        if lo <= x < hi:
            return i
    return -1


def _group_into_rows(words: list) -> list[tuple[float, list]]:
    """Group words by y-coordinate with tolerance, return sorted rows."""
    rows: dict[float, list] = {}
    for w in words:
        y0 = w[1]
        matched_y = None
        for ey in rows:
            if abs(ey - y0) <= 4:
                matched_y = ey
                break
        if matched_y is not None:
            rows[matched_y].append(w)
        else:
            rows[y0] = [w]
    return sorted(rows.items())


def _is_header_row(col_words: dict[int, list]) -> bool:
    """Check if any column contains a known team name prefix."""
    for col_idx in range(5):
        if not col_words[col_idx]:
            continue
        col_text = " ".join(w[4] for w in col_words[col_idx])
        for prefix in TEAM_PREFIXES:
            if prefix.lower() in col_text.lower():
                return True
    return False


def _should_skip(row_words: list) -> bool:
    """Check if this row should be skipped (title, footer, etc.)."""
    full_text = " ".join(w[4] for w in row_words)
    return any(pat in full_text for pat in SKIP_PATTERNS)


def parse_warne_cup_pdf(pdf_path: Path) -> dict[str, tuple[int, str]]:
    """Parse the Warne Cup PDF and return {name: (handicap, team_name)}.

    Uses word x-coordinates to assign players to the correct column/team
    in the 5-column layout.
    """
    doc = pymupdf.open(str(pdf_path))
    page = doc[0]
    words = page.get_text("words")

    sorted_rows = _group_into_rows(words)

    col_teams: dict[int, str | None] = {i: None for i in range(5)}
    players: dict[str, tuple[int, str]] = {}

    for _y, row_words in sorted_rows:
        if _should_skip(row_words):
            continue

        # Group words by column
        col_words: dict[int, list] = {i: [] for i in range(5)}
        for w in sorted(row_words, key=lambda w: w[0]):
            col = _assign_column(w[0])
            if col >= 0:
                col_words[col].append(w)

        # Check for header row
        if _is_header_row(col_words):
            for col_idx in range(5):
                if not col_words[col_idx]:
                    continue
                team_text = " ".join(w[4] for w in col_words[col_idx])
                team_text = team_text.replace("*", "").replace("jnrs", "").strip()
                # Only update if it looks like a team name
                if any(prefix.lower() in team_text.lower() for prefix in TEAM_PREFIXES):
                    col_teams[col_idx] = team_text
            continue

        # Parse player data from each column
        for col_idx in range(5):
            if not col_words[col_idx]:
                continue

            name_parts = []
            handicap = None

            for w in col_words[col_idx]:
                text = w[4].rstrip(",")
                if re.match(r"^-?\d+$", text):
                    handicap = int(text)
                else:
                    name_parts.append(text)

            if name_parts and handicap is not None:
                name = " ".join(name_parts)
                team = col_teams.get(col_idx) or "Unknown"
                players[name] = (handicap, team)

    doc.close()
    return players


def _normalise(name: str) -> str:
    """Normalise a name for fuzzy matching."""
    # Collapse multiple spaces, strip non-alpha
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", "", name.lower())).strip()


def _normalise_team(name: str) -> str:
    """Normalise a team name: replace curly apostrophes, strip whitespace."""
    return name.replace("\u2019", "'").replace("\u2018", "'").strip()


def _edit_distance(a: str, b: str) -> int:
    """Simple Levenshtein edit distance."""
    if len(a) < len(b):
        return _edit_distance(b, a)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (ca != cb)))
        prev = curr
    return prev[-1]


def _fuzzy_match(pdf_name: str, elo_lookup: dict[str, EloEntry]) -> EloEntry | None:
    """Try to match a PDF name to an ELO player using fuzzy matching.

    Handles abbreviated names (PDF may use shorter form) and minor typos.
    Requires at least 2 name parts to avoid false positives on single-word matches.
    """
    pdf_parts = set(pdf_name.split())
    if len(pdf_parts) < 2:
        return None

    # Pass 1: subset matching for abbreviated names
    best_match: EloEntry | None = None
    best_score = 0.0

    for elo_norm, elo_data in elo_lookup.items():
        elo_parts = set(elo_norm.split())
        if pdf_parts <= elo_parts:
            score = len(pdf_parts) / len(elo_parts)
        elif elo_parts <= pdf_parts:
            score = len(elo_parts) / len(pdf_parts)
        else:
            continue
        if score > best_score:
            best_score = score
            best_match = elo_data

    if best_match and best_score >= 0.5:
        return best_match

    # Pass 2: edit distance on the full normalised name (catches typos)
    best_dist = 3  # max allowed distance
    best_match = None
    for elo_norm, elo_data in elo_lookup.items():
        # Only compare candidates that share at least one word, to avoid O(N²)
        # over the entire dictionary and to limit false positives.
        if not (pdf_parts & set(elo_norm.split())):
            continue
        dist = _edit_distance(pdf_name, elo_norm)
        if dist < best_dist:
            best_dist = dist
            best_match = elo_data

    return best_match


def _build_elo_lookup(matches) -> dict[str, EloEntry]:
    """Return a {normalised_name: EloEntry} lookup over all rated players."""
    ratings = calculate_ratings(matches)
    lookup: dict[str, EloEntry] = {}
    for pr in ratings.values():
        lookup[_normalise(pr.name)] = EloEntry(
            name=pr.name,
            rating=pr.rating,
            division=pr.division,
            win_rate=pr.win_rate,
            singles_played=pr.singles_played,
        )
    return lookup


def _linear_fit(xs: list[float], ys: list[float]) -> tuple[float, float, float]:
    """Return (slope, intercept, pearson_r) for a linear y = slope*x + intercept fit."""
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / n
    var_x = sum((x - mean_x) ** 2 for x in xs) / n
    var_y = sum((y - mean_y) ** 2 for y in ys) / n
    slope = cov / var_x if var_x > 0 else 0.0
    intercept = mean_y - slope * mean_x
    r = cov / (var_x * var_y) ** 0.5 if var_x > 0 and var_y > 0 else 0.0
    return slope, intercept, r


def build_results() -> tuple[list[Result], list[tuple[str, int, str]], float, float, float, int]:
    """Parse PDF, load ELO data, match players, and compute the linear fit.

    Returns (results, not_found, slope, intercept, pearson_r, total_pdf_players).
    """
    warne = parse_warne_cup_pdf(PDF_PATH)
    elo_lookup = _build_elo_lookup(load_matches())

    matched: list[tuple[str, int, str, EloEntry]] = []
    not_found: list[tuple[str, int, str]] = []
    for wname, (hcap, team) in warne.items():
        norm = _normalise(wname)
        entry = elo_lookup.get(norm) or _fuzzy_match(norm, elo_lookup)
        if entry is None:
            not_found.append((wname, hcap, _normalise_team(team)))
        else:
            matched.append((wname, hcap, _normalise_team(team), entry))

    if len(matched) < 3:
        return [], not_found, 0.0, 0.0, 0.0, len(warne)

    slope, intercept, r = _linear_fit(
        [m[1] for m in matched], [m[3].rating for m in matched]
    )

    results: list[Result] = []
    for wname, hcap, team, entry in matched:
        expected = slope * hcap + intercept
        results.append(Result(
            name=wname, handicap=hcap, team=team,
            elo=entry.rating, expected=expected, diff=entry.rating - expected,
            division=entry.division, win_rate=entry.win_rate,
            singles_played=entry.singles_played,
        ))

    results.sort(key=lambda x: x.diff, reverse=True)
    return results, not_found, slope, intercept, r, len(warne)


def _print_player_row(r: Result, out, name_width: int = 30) -> None:
    out.write(
        f"  {r.name:<{name_width}} {r.handicap:>5} {r.elo:>7.0f} {r.expected:>7.0f} "
        f"{r.diff:>+6.0f} {r.division:>3} {r.win_rate * 100:>4.0f}% {r.singles_played:>3}\n"
    )


def _format_report(
    results: list[Result],
    not_found: list[tuple[str, int, str]],
    slope: float,
    intercept: float,
    pearson_r: float,
    total: int,
    out,
) -> None:
    """Write the full comparison report to *out*."""
    if not results:
        out.write("Too few matched players for analysis.\n")
        return

    # ── Overall comparison ──
    out.write("=" * 80 + "\n")
    out.write("  OVERALL COMPARISON: ELO vs Warne Cup Handicaps (±100 seeding)\n")
    out.write("=" * 80 + "\n")
    out.write(f"  Matched: {len(results)} of {total} players\n")
    out.write(f"  Linear fit: ELO ≈ {slope:.1f} × Handicap + {intercept:.0f}\n")
    out.write(f"  Correlation (Pearson r): {pearson_r:.3f}\n")
    if not_found:
        out.write(f"  Not found in league data: {len(not_found)} players\n")

    out.write(
        f"\n  {'Name':<30} {'H/cap':>5} {'ELO':>7} {'Exp.':>7} {'Diff':>6} "
        f"{'Div':>3} {'W%':>5} {'M':>3}\n"
    )
    out.write(f"  {'-' * 72}\n")

    out.write("\n  Stronger than handicap (league data says better than h/cap gives credit):\n")
    for r in results[:10]:
        _print_player_row(r, out)

    out.write("\n  Weaker than handicap (league data says worse than h/cap gives credit):\n")
    for r in results[-10:]:
        _print_player_row(r, out)

    # ── Team-specific analysis ──
    target_teams = ["Apex 4", "St Katharine's Trust 6", "Flick 1", "Irving 3"]
    for target in target_teams:
        _print_team_section(target, results, not_found, slope, intercept, out)

    # All not-found players
    if not_found:
        out.write(f"\n{'=' * 80}\n")
        out.write(f"  Players not found in league data ({len(not_found)}):\n")
        out.write(f"{'=' * 80}\n")
        for name, hcap, team in sorted(not_found, key=lambda x: x[2]):
            out.write(f"  {name:<30} H/cap {hcap:>3}  ({team})\n")


def _print_team_section(
    target: str,
    results: list[Result],
    not_found: list[tuple[str, int, str]],
    slope: float,
    intercept: float,
    out,
) -> None:
    """Write the team-specific section for *target* to *out*."""
    target_lc = target.lower()
    team_matched = [r for r in results if r.team and target_lc in r.team.lower()]
    team_nf = [nf for nf in not_found if nf[2] and target_lc in nf[2].lower()]

    out.write(f"\n{'=' * 85}\n")
    out.write(f"  {target}\n")
    out.write(f"{'=' * 85}\n")

    if not team_matched and not team_nf:
        out.write("  NO PLAYERS FOUND\n")
        return

    team_matched.sort(key=lambda r: r.elo, reverse=True)

    out.write(
        f"  {'Name':<28} {'H/cap':>5} {'ELO':>7} {'Exp.':>7} {'Diff':>6} "
        f"{'Div':>4} {'W%':>5} {'M':>3}  Verdict\n"
    )
    out.write(f"  {'-' * 81}\n")

    for r in team_matched:
        if abs(r.diff) > 50:
            verdict = ">> Stronger than handicap" if r.diff > 0 else "<< Weaker than handicap"
        else:
            verdict = "~  Fair"
        out.write(
            f"  {r.name:<28} {r.handicap:>5} {r.elo:>7.0f} {r.expected:>7.0f} "
            f"{r.diff:>+6.0f} {r.division:>4} {r.win_rate * 100:>4.0f}% "
            f"{r.singles_played:>3}  {verdict}\n"
        )

    for name, hcap, _team in team_nf:
        exp = slope * hcap + intercept
        out.write(
            f"  {name:<28} {hcap:>5} {'?':>7} {exp:>7.0f} {'?':>6} "
            f"{'?':>4} {'?':>5} {'?':>3}  NOT FOUND\n"
        )

    n_total = len(team_matched) + len(team_nf)
    avg_elo = sum(r.elo for r in team_matched) / len(team_matched) if team_matched else 0.0
    avg_hcap = (sum(r.handicap for r in team_matched) + sum(nf[1] for nf in team_nf)) / n_total
    avg_exp = (
        sum(r.expected for r in team_matched)
        + sum(slope * nf[1] + intercept for nf in team_nf)
    ) / n_total
    out.write(
        f"\n  Team avg: ELO {avg_elo:.0f} | Handicap avg {avg_hcap:.1f} "
        f"| Expected ELO from handicap {avg_exp:.0f}\n"
    )


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    results, not_found, slope, intercept, r, total = build_results()
    print(f"Parsed {total} players from Warne Cup PDF")

    _format_report(results, not_found, slope, intercept, r, total, sys.stdout)
    with open(OUTPUT_PATH, "w") as f:
        _format_report(results, not_found, slope, intercept, r, total, f)

    print(f"\nResults saved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
