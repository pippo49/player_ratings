"use strict";

/* ════════════════════════════════════════════════════════
   State
   ════════════════════════════════════════════════════════ */

const state = {
  data: null,
  players: new Map(),   // id -> player
  teams: new Map(),     // name -> team
  view: "players",
  playerQuery: "",
  playerDiv: 0,         // 0 = all
  reliableOnly: false,
  teamQuery: "",
  teamDiv: 0,
  us: "",
  them: "",
  callUp: new Set(),        // lower club sides players can be drawn from
  unavailable: new Set(),   // player ids ticked out for this fixture
  target: 7,                // points per match needed for promotion
  polling: null,
};

const $ = (sel) => document.querySelector(sel);
const el = (tag, cls) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  return node;
};

/* ════════════════════════════════════════════════════════
   Rating maths
   ════════════════════════════════════════════════════════ */

/** Probability that a player rated `a` beats a player rated `b`. */
function expected(a, b) {
  return 1 / (1 + Math.pow(10, (b - a) / 400));
}

/**
 * Distribution over the number of singles won out of `probs.length`,
 * treating each singles match as independent. Returns an array where
 * index k is P(exactly k wins).
 */
function winDistribution(probs) {
  let dist = [1];
  for (const p of probs) {
    const next = new Array(dist.length + 1).fill(0);
    for (let k = 0; k < dist.length; k++) {
      next[k] += dist[k] * (1 - p);
      next[k + 1] += dist[k] * p;
    }
    dist = next;
  }
  return dist;
}

/**
 * Evaluate a team match: 9 singles as a round robin between the two trios,
 * plus the doubles point, for 10 points in total.
 *
 * The doubles pairing is assumed to be each side's strongest two, and its
 * strength is modelled as the mean of their singles ratings.
 */
function evaluateLineup(ours, theirs) {
  const singles = [];
  const grid = ours.map((a) => theirs.map((b) => {
    const p = expected(a.rating, b.rating);
    singles.push(p);
    return p;
  }));

  const pair = (side) => {
    const top = side.map((p) => p.rating).sort((a, b) => b - a).slice(0, 2);
    return top.reduce((sum, r) => sum + r, 0) / top.length;
  };
  const doublesProb = expected(pair(ours), pair(theirs));

  const expectedSingles = singles.reduce((sum, p) => sum + p, 0);
  const dist = winDistribution(singles.concat([doublesProb]));
  const points = singles.length + 1;
  const needed = Math.floor(points / 2) + 1;

  let win = 0, draw = 0;
  for (let k = 0; k < dist.length; k++) {
    if (k >= needed) win += dist[k];
    else if (points % 2 === 0 && k === points / 2) draw += dist[k];
  }

  return {
    grid,
    doublesProb,
    expectedSingles,
    expectedPoints: expectedSingles + doublesProb,
    points,
    winProb: win,
    drawProb: draw,
    dist,
  };
}

/**
 * The best trio is simply the three highest-rated available players.
 *
 * Because all nine singles are a round robin, expected points decompose into
 * one independent term per selected player, so maximising the total is just
 * picking the three largest terms — and each term is increasing in rating.
 * Searching every combination provably cannot beat a sort.
 */
function bestTrio(squad) {
  return squad.slice().sort((a, b) => b.rating - a.rating).slice(0, 3);
}

/* ════════════════════════════════════════════════════════
   Formatting
   ════════════════════════════════════════════════════════ */

const fmtRating = (r) => Math.round(r).toString();

/** "Karl Weber" -> "Karl W." — keeps the head-to-head grid readable on a phone. */
function shortName(name) {
  const parts = name.trim().split(/\s+/);
  return parts.length < 2 ? name : `${parts[0]} ${parts[parts.length - 1][0]}.`;
}

const fmtPct = (p) => `${Math.round(p * 100)}%`;

/** Like fmtPct, but never rounds a real chance away to a flat 0% or 100%. */
function fmtChance(p) {
  if (p > 0 && p < 0.005) return "<1%";
  if (p < 1 && p > 0.995) return ">99%";
  return fmtPct(p);
}
const fmtScore = (n) => n.toFixed(1);

function ordinal(n) {
  const rem100 = n % 100;
  if (rem100 >= 11 && rem100 <= 13) return `${n}th`;
  return `${n}${["th", "st", "nd", "rd"][n % 10] || "th"}`;
}

function formatDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

function relativeTime(iso) {
  if (!iso) return "never";
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} hr ago`;
  return `${Math.round(hours / 24)} d ago`;
}

/* ════════════════════════════════════════════════════════
   Data loading
   ════════════════════════════════════════════════════════ */

async function loadRatings() {
  const res = await fetch("/api/ratings");
  if (!res.ok) throw new Error(`Ratings request failed (${res.status})`);
  const data = await res.json();

  state.data = data;
  state.players = new Map(data.players.map((p) => [p.id, p]));
  state.teams = new Map(data.teams.map((t) => [t.name, t]));

  $("#min-matches-label").textContent = `(${data.min_matches}+ matches)`;
  renderMeta();
  buildChips();
  buildTeamOptions();
  renderAll();
}

function renderMeta() {
  const d = state.data;
  if (!d || !d.match_count) {
    $("#meta").textContent = "No results downloaded yet";
    return;
  }
  const parts = [d.season, `${d.match_count} matches`, `${d.player_count} players`];
  if (d.last_match_date) parts.push(`to ${formatDate(d.last_match_date)}`);
  $("#meta").textContent = parts.join(" · ");
}

/* ════════════════════════════════════════════════════════
   Filters
   ════════════════════════════════════════════════════════ */

function buildChips() {
  const divisions = [...new Set(state.data.players.map((p) => p.division))].sort();

  const build = (host, key, rerender) => {
    host.textContent = "";
    const add = (label, value) => {
      const chip = el("button", "chip");
      chip.type = "button";
      chip.textContent = label;
      chip.setAttribute("aria-pressed", String(state[key] === value));
      chip.onclick = () => {
        state[key] = value;
        build(host, key, rerender);
        rerender();
      };
      host.append(chip);
    };
    add("All divisions", 0);
    divisions.forEach((d) => add(`Div ${d}`, d));
  };

  build($("#chips-player"), "playerDiv", renderPlayers);
  build($("#chips-team"), "teamDiv", renderTeams);
}

function matches(haystack, needle) {
  return haystack.toLowerCase().includes(needle.trim().toLowerCase());
}

/* ════════════════════════════════════════════════════════
   Players view
   ════════════════════════════════════════════════════════ */

function filteredPlayers() {
  return state.data.players.filter((p) =>
    (!state.playerDiv || p.division === state.playerDiv) &&
    (!state.reliableOnly || p.reliable) &&
    (!state.playerQuery || matches(p.name, state.playerQuery) || matches(p.team, state.playerQuery))
  );
}

function renderPlayers() {
  const host = $("#list-players");
  host.textContent = "";

  if (!state.data.match_count) {
    host.append(emptyState("No results downloaded yet.", "Tap the refresh button to fetch the season."));
    $("#count-players").textContent = "";
    return;
  }

  const list = filteredPlayers();
  $("#count-players").textContent = list.length
    ? `${list.length} player${list.length === 1 ? "" : "s"} · ranked by rating`
    : "";

  if (!list.length) {
    host.append(emptyState("No players match that search."));
    return;
  }

  list.slice(0, 300).forEach((p, i) => host.append(playerRow(p, i + 1)));
  if (list.length > 300) {
    const more = el("p", "count");
    more.textContent = `Showing the top 300 of ${list.length} — narrow the search to see more.`;
    host.append(more);
  }
}

function playerRow(p, rank) {
  const row = el("button", "row");
  row.type = "button";

  const rankEl = el("div", "rank");
  rankEl.textContent = rank;

  const main = el("div", "row-main");
  const name = el("div", "row-name");
  name.textContent = p.name;
  if (!p.reliable) {
    const flag = el("span", "provisional");
    flag.textContent = " *";
    flag.title = "Provisional — few matches played";
    name.append(flag);
  }
  const sub = el("div", "row-sub");
  const badge = el("span", "badge");
  badge.textContent = `D${p.division}`;
  sub.append(badge, document.createTextNode(p.team));
  main.append(name, sub);

  const end = el("div", "row-end");
  const rating = el("div", "rating");
  rating.textContent = fmtRating(p.rating);
  const sub2 = el("small");
  sub2.textContent = `${fmtPct(p.win_rate)} of ${p.played}`;
  end.append(rating, sub2);

  row.append(rankEl, main, end);
  row.onclick = () => openPlayerSheet(p);
  return row;
}

function emptyState(title, detail) {
  const box = el("div", "empty");
  box.append(document.createTextNode(title));
  if (detail) {
    box.append(el("br"), document.createTextNode(detail));
  }
  return box;
}

/* ════════════════════════════════════════════════════════
   Teams view
   ════════════════════════════════════════════════════════ */

function teamStrength(team) {
  const top = team.players
    .map((m) => state.players.get(m.id))
    .filter(Boolean)
    .slice(0, 3);
  if (!top.length) return 0;
  return top.reduce((sum, p) => sum + p.rating, 0) / top.length;
}

function filteredTeams() {
  return state.data.teams
    .filter((t) =>
      (!state.teamDiv || t.division === state.teamDiv) &&
      (!state.teamQuery || matches(t.name, state.teamQuery))
    )
    .sort((a, b) => teamStrength(b) - teamStrength(a));
}

function renderTeams() {
  const host = $("#list-teams");
  host.textContent = "";

  if (!state.data.match_count) {
    host.append(emptyState("No results downloaded yet.", "Tap the refresh button to fetch the season."));
    $("#count-teams").textContent = "";
    return;
  }

  const list = filteredTeams();
  $("#count-teams").textContent = list.length
    ? `${list.length} team${list.length === 1 ? "" : "s"} · ranked by top-3 average`
    : "";

  if (!list.length) {
    host.append(emptyState("No teams match that search."));
    return;
  }

  list.forEach((t, i) => {
    const row = el("button", "row");
    row.type = "button";

    const rank = el("div", "rank");
    rank.textContent = i + 1;

    const main = el("div", "row-main");
    const name = el("div", "row-name");
    name.textContent = t.name;
    const sub = el("div", "row-sub");
    const badge = el("span", "badge");
    badge.textContent = `D${t.division}`;
    sub.append(badge, document.createTextNode(
      `${t.players.length} player${t.players.length === 1 ? "" : "s"} used`
    ));
    main.append(name, sub);

    const end = el("div", "row-end");
    const rating = el("div", "rating");
    rating.textContent = fmtRating(teamStrength(t));
    const small = el("small");
    small.textContent = "top 3 avg";
    end.append(rating, small);

    row.append(rank, main, end);
    row.onclick = () => openTeamSheet(t);
    host.append(row);
  });
}

/* ════════════════════════════════════════════════════════
   Selection view
   ════════════════════════════════════════════════════════ */

function buildTeamOptions() {
  const list = $("#team-options");
  list.textContent = "";
  state.data.teams
    .slice()
    .sort((a, b) => a.name.localeCompare(b.name))
    .forEach((t) => {
      const opt = el("option");
      opt.value = t.name;
      opt.label = `Division ${t.division}`;
      list.append(opt);
    });
}

/** "Apex 4" -> "Apex". Club teams are named for the club plus a number. */
function clubOf(name) {
  return name.replace(/\s+\d+[A-Za-z]?$/, "").trim();
}

/** Resolve a typed team name to a team, tolerating case and partial entry. */
function resolveTeam(query) {
  if (!query.trim()) return null;
  const exact = state.teams.get(query);
  if (exact) return exact;
  const hits = state.data.teams.filter((t) => matches(t.name, query));
  return hits.length === 1 ? hits[0] : null;
}

function squadFor(team) {
  return team.players
    .map((m) => ({ ...state.players.get(m.id), appearances: m.appearances, from: team.name }))
    .filter((p) => p.id)
    .sort((a, b) => b.rating - a.rating);
}

/**
 * Teams in the same club playing at a lower standard, whose players can be
 * called up. A higher division number is a lower standard.
 */
function feederTeams(team) {
  const club = clubOf(team.name);
  return state.data.teams
    .filter((t) => t.name !== team.name && clubOf(t.name) === club && t.division > team.division)
    .sort((a, b) => a.division - b.division);
}

/** The full pool available to a captain: their own squad plus any called-up feeders. */
function pooledSquad(team) {
  const seen = new Set();
  const pool = [];
  for (const source of [team, ...feederTeams(team).filter((t) => state.callUp.has(t.name))]) {
    for (const p of squadFor(source)) {
      if (seen.has(p.id)) continue;
      seen.add(p.id);
      pool.push(p);
    }
  }
  return pool.sort((a, b) => b.rating - a.rating);
}

function availableFrom(pool) {
  return pool.filter((p) => !state.unavailable.has(p.id));
}

function renderLineup() {
  const host = $("#lineup-body");
  host.textContent = "";

  if (!state.data.match_count) {
    host.append(emptyState("No results downloaded yet.", "Tap the refresh button to fetch the season."));
    return;
  }

  const us = resolveTeam(state.us);
  if (!us) {
    host.append(introCard());
    return;
  }

  host.append(callUpCard(us));

  const pool = pooledSquad(us);
  const squad = availableFrom(pool);

  if (squad.length < 3) {
    host.append(noteCard("At least three players need to be available."));
  } else {
    host.append(seasonCard(us, squad));
    host.append(fixtureCard(us, squad));
  }

  host.append(squadCard(us, pool));
}

function introCard() {
  const card = el("div", "card");
  const h = el("h2");
  h.textContent = "Pick the team you select for";
  const p = el("p", "hint");
  p.textContent =
    `Ratings carry over from ${state.data.season}, so they are the best guide to ` +
    "form going into 2026/27. Choose your team and anyone you can call up from " +
    "a lower club side, and every fixture is scored over all 10 points.";
  card.append(h, p);
  return card;
}

function noteCard(text) {
  const card = el("div", "card");
  const p = el("p", "hint");
  p.textContent = text;
  card.append(p);
  return card;
}

/** Lower club sides whose players this captain can call up. */
function callUpCard(team) {
  const card = el("div", "card");
  const h = el("h2");
  h.textContent = "Call-ups";
  card.append(h);

  const feeders = feederTeams(team);
  if (!feeders.length) {
    const p = el("p", "hint");
    p.textContent = `No lower ${clubOf(team.name)} side found in the data.`;
    card.append(p);
    return card;
  }

  const hint = el("p", "hint");
  hint.textContent = "Lower club sides you can draw players from.";
  card.append(hint);

  const box = el("div", "squad");
  feeders.forEach((t) => {
    const label = el("label");
    const check = el("input");
    check.type = "checkbox";
    check.checked = state.callUp.has(t.name);
    check.onchange = () => {
      if (check.checked) state.callUp.add(t.name);
      else state.callUp.delete(t.name);
      renderLineup();
    };
    const nm = el("span", "nm");
    nm.textContent = t.name;
    const rt = el("span", "rt");
    rt.textContent = `Div ${t.division}`;
    label.append(check, nm, rt);
    box.append(label);
  });
  card.append(box);
  return card;
}

/* ── Season outlook ───────────────────────────────────── */

/** Expected points against every other team in the division, and the average. */
function seasonOutlook(team, squad) {
  const trio = bestTrio(squad);
  const rivals = state.data.teams
    .filter((t) => t.division === team.division && t.name !== team.name)
    .map((t) => {
      const theirs = bestTrio(squadFor(t));
      if (theirs.length < 3) return null;
      const result = evaluateLineup(trio, theirs);
      return { team: t, ...result };
    })
    .filter(Boolean)
    .sort((a, b) => a.expectedPoints - b.expectedPoints);

  const average = rivals.length
    ? rivals.reduce((sum, r) => sum + r.expectedPoints, 0) / rivals.length
    : 0;
  return { trio, rivals, average };
}

function seasonCard(team, squad) {
  const { trio, rivals, average } = seasonOutlook(team, squad);
  const target = state.target;

  const card = el("div", "card");
  const h = el("h2");
  h.textContent = "Season outlook";
  const hint = el("p", "hint");
  hint.textContent =
    `Your strongest available three against every other side in Division ` +
    `${team.division}, assuming each fields its best three.`;
  card.append(h, hint);

  if (!rivals.length) {
    card.append(noteCard("No other teams in this division to compare against."));
    return card;
  }

  const score = el("div", "scoreline");
  const avg = el("b");
  avg.textContent = fmtScore(average);
  const of = el("span");
  of.textContent = `of ${state.data.points_per_match} per match`;
  score.append(avg, of);
  card.append(score);

  const verdict = el("div", "prob");
  const strong = el("strong");
  const gap = average - target;
  strong.textContent = gap >= 0 ? "On track" : "Short of target";
  strong.className = gap >= 0 ? "good" : "bad";
  verdict.append(strong, document.createTextNode(
    ` — ${gap >= 0 ? "+" : ""}${gap.toFixed(1)} against a ${fmtScore(target)} target`
  ));
  card.append(verdict);

  const bar = el("div", "bar");
  const fill = el("i");
  fill.style.width = `${Math.min(100, Math.round((average / state.data.points_per_match) * 100))}%`;
  if (gap < 0) fill.classList.add("short");
  bar.append(fill);
  card.append(bar);

  const picks = el("div", "picks");
  trio.forEach((p, i) => {
    const pick = el("div", "pick");
    const num = el("span", "num");
    num.textContent = i + 1;
    const nm = el("span", "nm");
    nm.textContent = p.name + (p.reliable ? "" : " *");
    const rt = el("span", "rt");
    rt.textContent = fmtRating(p.rating);
    pick.append(num, nm, rt);
    picks.append(pick);
  });
  card.append(picks);

  const wrap = el("div", "table-wrap");
  const caption = el("p", "hint");
  caption.textContent = "Expected points per fixture, hardest first";
  const table = el("table");
  const thead = el("thead");
  const hrow = el("tr");
  ["Opponent", "Pts", "Win"].forEach((label) => {
    const th = el("th");
    th.textContent = label;
    hrow.append(th);
  });
  thead.append(hrow);

  const tbody = el("tbody");
  rivals.forEach((r) => {
    const tr = el("tr");
    const th = el("th");
    th.textContent = r.team.name;
    const pts = el("td", `pc ${r.expectedPoints >= target ? "win" : "lose"}`);
    pts.textContent = fmtScore(r.expectedPoints);
    const win = el("td", "pc");
    win.textContent = fmtChance(r.winProb);
    tr.append(th, pts, win);
    tbody.append(tr);
  });
  table.append(thead, tbody);
  wrap.append(caption, table);
  card.append(wrap);

  const foot = el("p", "hint");
  foot.textContent =
    `Averaging ${fmtScore(target)} is the promotion target you set. Points are 9 ` +
    "singles plus the doubles. Fixtures you are expected to fall short in are the " +
    "ones where a call-up changes the season.";
  card.append(foot);

  // The doubles point is inferred, not scraped directly. Say so when it looks wrong.
  const doubles = state.data.doubles;
  if (doubles && !doubles.trustworthy) {
    const warn = el("p", "hint warn-note");
    warn.textContent =
      `The doubles point could not be recovered from ${doubles.anomalies} of ` +
      `${doubles.matches} matches, so the 10th point is a guess here. ` +
      "Run check_doubles.py for the detail.";
    card.append(warn);
  }
  return card;
}

/* ── One fixture in detail ────────────────────────────── */

function fixtureCard(us, squad) {
  const card = el("div", "card");
  const h = el("h2");
  h.textContent = "A single fixture";
  const hint = el("p", "hint");
  hint.textContent = "Pick an opponent to see the match broken down.";
  card.append(h, hint);

  const field = el("div", "field");
  const input = el("input", "search");
  input.setAttribute("list", "team-options");
  input.placeholder = "Opponent…";
  input.value = state.them;
  input.autocomplete = "off";
  input.oninput = debounce(() => {
    state.them = input.value;
    renderLineup();
  }, 150);
  field.append(input);
  card.append(field);

  const them = resolveTeam(state.them);
  if (!them) return card;
  if (them.name === us.name) {
    card.append(noteCard("Pick a different team."));
    return card;
  }

  const theirs = bestTrio(squadFor(them));
  if (theirs.length < 3) {
    card.append(noteCard("Not enough rated players for that team."));
    return card;
  }

  const trio = bestTrio(squad);
  const result = evaluateLineup(trio, theirs);

  const score = el("div", "scoreline");
  const ours = el("b");
  ours.textContent = fmtScore(result.expectedPoints);
  const dash = el("span");
  dash.textContent = "–";
  const other = el("b");
  other.textContent = fmtScore(result.points - result.expectedPoints);
  score.append(ours, dash, other);

  const prob = el("div", "prob");
  const strong = el("strong");
  strong.textContent = fmtChance(result.winProb);
  prob.append(strong, document.createTextNode(" chance of winning the team match"));
  if (result.drawProb > 0.005) {
    prob.append(document.createTextNode(` · ${fmtChance(result.drawProb)} draw at 5–5`));
  }
  card.append(score, prob);

  const split = el("p", "hint");
  split.textContent =
    `${fmtScore(result.expectedSingles)} of 9 singles, plus ` +
    `${fmtChance(result.doublesProb)} on the doubles.`;
  card.append(split);

  card.append(matrixTable(result, trio, theirs));
  return card;
}

function matrixTable(result, trio, theirBest) {
  const wrap = el("div", "table-wrap");
  const caption = el("p", "hint");
  caption.textContent = "Head-to-head win chance";
  const table = el("table");

  const thead = el("thead");
  const hrow = el("tr");
  hrow.append(el("th"));
  theirBest.forEach((p) => {
    const th = el("th");
    th.textContent = shortName(p.name);
    th.title = `${p.name} (${fmtRating(p.rating)})`;
    hrow.append(th);
  });
  thead.append(hrow);

  const tbody = el("tbody");
  trio.forEach((p, i) => {
    const tr = el("tr");
    const th = el("th");
    th.textContent = shortName(p.name);
    th.title = `${p.name} (${fmtRating(p.rating)})`;
    tr.append(th);
    result.grid[i].forEach((prob) => {
      const td = el("td", `pc ${prob >= 0.5 ? "win" : "lose"}`);
      td.textContent = fmtPct(prob);
      tr.append(td);
    });
    tbody.append(tr);
  });

  table.append(thead, tbody);
  wrap.append(caption, table);
  return wrap;
}

function squadCard(team, pool) {
  const card = el("div", "card");
  const h = el("h2");
  h.textContent = "Availability";
  const hint = el("p", "hint");
  hint.textContent = "Untick anyone who cannot play.";
  card.append(h, hint);

  const box = el("div", "squad");
  pool.forEach((p) => {
    const label = el("label");
    const check = el("input");
    check.type = "checkbox";
    check.checked = !state.unavailable.has(p.id);
    if (!check.checked) label.classList.add("out");
    check.onchange = () => {
      if (check.checked) state.unavailable.delete(p.id);
      else state.unavailable.add(p.id);
      renderLineup();
    };
    const nm = el("span", "nm");
    nm.textContent = p.name + (p.reliable ? "" : " *");
    const rt = el("span", "rt");
    rt.textContent = p.from === team.name
      ? fmtRating(p.rating)
      : `${fmtRating(p.rating)} · ${p.from}`;
    label.append(check, nm, rt);
    box.append(label);
  });
  card.append(box);
  return card;
}

/* ════════════════════════════════════════════════════════
   Sheets
   ════════════════════════════════════════════════════════ */

function openSheet(build) {
  const body = $("#sheet-body");
  body.textContent = "";
  build(body);
  $("#sheet").classList.remove("hidden");
  $("#scrim").classList.remove("hidden");
}

function closeSheet() {
  $("#sheet").classList.add("hidden");
  $("#scrim").classList.add("hidden");
  if (state.polling) { clearInterval(state.polling); state.polling = null; }
}

function openPlayerSheet(p) {
  openSheet((body) => {
    const h = el("h2");
    h.textContent = p.name;
    const sub = el("p", "sub");
    sub.textContent = `${p.team} · Division ${p.division}`;
    body.append(h, sub);

    const overall = state.data.players.findIndex((x) => x.id === p.id) + 1;
    const inDiv = state.data.players
      .filter((x) => x.division === p.division)
      .findIndex((x) => x.id === p.id) + 1;

    const stats = el("div", "stats");
    const add = (value, label) => {
      const stat = el("div", "stat");
      const b = el("b");
      b.textContent = value;
      const s = el("span");
      s.textContent = label;
      stat.append(b, s);
      stats.append(stat);
    };
    add(fmtRating(p.rating), p.reliable ? "ELO rating" : "ELO rating (provisional)");
    add(fmtPct(p.win_rate), "Singles win rate");
    add(`${p.won}/${p.played}`, "Singles won");
    add(ordinal(overall), "Overall rank");
    add(ordinal(inDiv), `Rank in Division ${p.division}`);
    if (!p.reliable) {
      add(`${state.data.min_matches - p.played}`, "More matches to be rated");
    }
    body.append(stats);
  });
}

function openTeamSheet(t) {
  openSheet((body) => {
    const h = el("h2");
    h.textContent = t.name;
    const sub = el("p", "sub");
    sub.textContent = `Division ${t.division} · top-3 average ${fmtRating(teamStrength(t))}`;
    body.append(h, sub);

    const list = el("div", "list");
    squadFor(t).forEach((p, i) => list.append(playerRow(p, i + 1)));
    body.append(list);

    const actions = el("div", "sheet-actions");
    const action = el("button", "action primary");
    action.type = "button";
    action.textContent = "Select for this team";
    action.onclick = () => {
      state.us = t.name;
      $("#pick-us").value = t.name;
      const nearest = feederTeams(t)[0];
      state.callUp = new Set(nearest ? [nearest.name] : []);
      state.unavailable = new Set();
      closeSheet();
      switchView("lineup");
    };
    actions.append(action);
    body.append(actions);
  });
}

/* ════════════════════════════════════════════════════════
   Update flow
   ════════════════════════════════════════════════════════ */

function openUpdateSheet() {
  openSheet((body) => {
    const h = el("h2");
    h.textContent = "Fetch latest results";
    const sub = el("p", "sub");
    sub.textContent = state.data && state.data.generated_at
      ? `Ratings calculated ${relativeTime(state.data.generated_at)}.`
      : "";
    body.append(h, sub);

    const actions = el("div", "sheet-actions");
    const log = el("div", "log hidden");

    const makeButton = (mode, label, detail, primary) => {
      const btn = el("button", `action${primary ? " primary" : ""}`);
      btn.type = "button";
      btn.append(document.createTextNode(label));
      const small = el("small");
      small.textContent = detail;
      btn.append(small);
      btn.onclick = () => startUpdate(mode, actions, log);
      return btn;
    };

    actions.append(
      makeButton("update", "Check for new results",
        "Scrapes all divisions and adds anything new", true),
      makeButton("refresh", "Full re-download",
        "Replaces the cache from scratch — slower", false),
    );
    body.append(actions, log);
  });
}

async function startUpdate(mode, actions, log) {
  actions.querySelectorAll("button").forEach((b) => { b.disabled = true; });
  log.classList.remove("hidden");
  log.textContent = "Starting…";
  $("#btn-update").classList.add("busy");

  try {
    const res = await fetch("/api/update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    });
    if (!res.ok && res.status !== 409) throw new Error(`Server said ${res.status}`);
    pollUpdate(actions, log);
  } catch (err) {
    finishUpdate(actions, log, String(err));
  }
}

function pollUpdate(actions, log) {
  if (state.polling) clearInterval(state.polling);
  state.polling = setInterval(async () => {
    try {
      const status = await (await fetch("/api/update")).json();
      log.textContent = status.log.join("\n");
      log.scrollTop = log.scrollHeight;
      if (!status.running) {
        clearInterval(state.polling);
        state.polling = null;
        await loadRatings();
        finishUpdate(actions, log, status.error);
      }
    } catch (err) {
      clearInterval(state.polling);
      state.polling = null;
      finishUpdate(actions, log, String(err));
    }
  }, 1500);
}

function finishUpdate(actions, log, error) {
  $("#btn-update").classList.remove("busy");
  actions.querySelectorAll("button").forEach((b) => { b.disabled = false; });
  if (error) {
    const line = el("div", "err");
    line.textContent = `\n${error}`;
    log.append(line);
  }
}

/* ════════════════════════════════════════════════════════
   Views and wiring
   ════════════════════════════════════════════════════════ */

function switchView(view) {
  state.view = view;
  ["players", "teams", "lineup"].forEach((name) => {
    $(`#view-${name}`).classList.toggle("hidden", name !== view);
  });
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.view === view);
  });
  window.scrollTo(0, 0);
  renderAll();
}

function renderAll() {
  if (!state.data) return;
  if (state.view === "players") renderPlayers();
  else if (state.view === "teams") renderTeams();
  else renderLineup();
}

function debounce(fn, ms) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

function wire() {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.onclick = () => switchView(tab.dataset.view);
  });

  $("#q-player").oninput = debounce((e) => {
    state.playerQuery = e.target.value;
    renderPlayers();
  }, 120);

  $("#q-team").oninput = debounce((e) => {
    state.teamQuery = e.target.value;
    renderTeams();
  }, 120);

  $("#reliable-only").onchange = (e) => {
    state.reliableOnly = e.target.checked;
    renderPlayers();
  };

  $("#pick-us").oninput = debounce((e) => {
    state.us = e.target.value;
    // A new team means a new club, so call-ups and availability start clean.
    state.callUp = new Set();
    state.unavailable = new Set();
    const team = resolveTeam(state.us);
    // Default to the side directly below — the usual call-up route. Any
    // others can be ticked on explicitly.
    const nearest = team && feederTeams(team)[0];
    if (nearest) state.callUp.add(nearest.name);
    renderLineup();
  }, 150);

  $("#target").oninput = debounce((e) => {
    const value = parseFloat(e.target.value);
    state.target = Number.isFinite(value) ? Math.min(10, Math.max(0, value)) : 7;
    renderLineup();
  }, 200);

  $("#btn-update").onclick = openUpdateSheet;
  $("#scrim").onclick = closeSheet;
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeSheet();
  });
}

wire();
loadRatings().catch((err) => {
  $("#meta").textContent = `Could not load ratings — ${err.message}`;
});
