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
  benched: { us: new Set(), them: new Set() },
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

/** Evaluate one 3-a-side round robin: every one of ours plays every one of theirs. */
function evaluateLineup(ours, theirs) {
  const probs = [];
  const grid = ours.map((a) => theirs.map((b) => {
    const p = expected(a.rating, b.rating);
    probs.push(p);
    return p;
  }));
  const expectedWins = probs.reduce((sum, p) => sum + p, 0);
  const dist = winDistribution(probs);
  const total = probs.length;
  // A 9-point match is won outright at 5; a drawn rubber is possible only
  // when both sides are short, so handle any even total generically.
  const needed = Math.floor(total / 2) + 1;
  let win = 0, draw = 0;
  for (let k = 0; k < dist.length; k++) {
    if (k >= needed) win += dist[k];
    else if (total % 2 === 0 && k === total / 2) draw += dist[k];
  }
  return { grid, expectedWins, winProb: win, drawProb: draw, total };
}

/** Every k-sized combination of `items`. */
function combinations(items, k) {
  const out = [];
  const pick = (start, chosen) => {
    if (chosen.length === k) { out.push(chosen.slice()); return; }
    for (let i = start; i <= items.length - (k - chosen.length); i++) {
      chosen.push(items[i]);
      pick(i + 1, chosen);
      chosen.pop();
    }
  };
  pick(0, []);
  return out;
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
   Lineup view
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
    .map((m) => ({ ...state.players.get(m.id), appearances: m.appearances }))
    .filter((p) => p.id)
    .sort((a, b) => b.rating - a.rating);
}

function available(team, side) {
  return squadFor(team).filter((p) => !state.benched[side].has(p.id));
}

function renderLineup() {
  const host = $("#lineup-body");
  host.textContent = "";

  if (!state.data.match_count) {
    host.append(emptyState("No results downloaded yet.", "Tap the refresh button to fetch the season."));
    return;
  }

  const us = resolveTeam(state.us);
  const them = resolveTeam(state.them);

  if (!us || !them) {
    host.append(introCard());
    return;
  }
  if (us.name === them.name) {
    host.append(noteCard("Pick two different teams."));
    return;
  }

  const ourSquad = available(us, "us");
  const theirSquad = available(them, "them");

  if (ourSquad.length < 3 || theirSquad.length < 3) {
    host.append(noteCard("Both sides need at least three available players."));
  } else {
    host.append(resultCard(ourSquad, theirSquad, us, them));
  }

  host.append(squadCard(us, "us", "Your squad — untick anyone unavailable"));
  host.append(squadCard(them, "them", "Their squad — untick anyone you know is out"));
}

function introCard() {
  const card = el("div", "card");
  const h = el("h2");
  h.textContent = "Pick your team and the opposition";
  const p = el("p", "hint");
  p.textContent =
    "Ratings carry over from " + state.data.season + ", so they are the best guide to " +
    "form going into 2026/27. Choose both teams and every three-player lineup is " +
    "scored against theirs, all nine singles at a time.";
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

function resultCard(ourSquad, theirSquad, us, them) {
  // Their likely three: strongest available. Ours: whichever trio scores best.
  const theirBest = theirSquad.slice(0, 3);
  // Bound the search — beyond the top 20 available, nobody makes a best lineup.
  const candidates = ourSquad.slice(0, 20);
  const ranked = combinations(candidates, 3)
    .map((trio) => ({ trio, ...evaluateLineup(trio, theirBest) }))
    .sort((a, b) => b.expectedWins - a.expectedWins);

  const best = ranked[0];
  const card = el("div", "card");

  const h = el("h2");
  h.textContent = "Best lineup";
  const hint = el("p", "hint");
  hint.textContent = `${us.name} vs ${them.name} — against their strongest three available.`;
  card.append(h, hint);

  const score = el("div", "scoreline");
  const ours = el("b");
  ours.textContent = fmtScore(best.expectedWins);
  const dash = el("span");
  dash.textContent = "–";
  const theirs = el("b");
  theirs.textContent = fmtScore(best.total - best.expectedWins);
  score.append(ours, dash, theirs);

  const prob = el("div", "prob");
  const strong = el("strong");
  strong.textContent = fmtChance(best.winProb);
  prob.append(strong, document.createTextNode(" chance of winning the rubber"));
  if (best.drawProb > 0.005) {
    prob.append(document.createTextNode(` · ${fmtChance(best.drawProb)} draw`));
  }

  const bar = el("div", "bar");
  const fill = el("i");
  fill.style.width = `${Math.round(best.winProb * 100)}%`;
  bar.append(fill);

  card.append(score, prob, bar);

  const picks = el("div", "picks");
  best.trio.forEach((p, i) => {
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

  card.append(matrixTable(best, theirBest));

  const footnote = el("p", "hint");
  footnote.textContent =
    "Expected singles won out of " + best.total + ". Each singles is treated as " +
    "independent, so the rubber odds are a guide rather than a guarantee. " +
    "* marks a provisional rating from few matches.";
  card.append(footnote);

  if (ranked.length > 1) {
    card.append(alternatives(ranked.slice(1, 5)));
  }
  return card;
}

function matrixTable(best, theirBest) {
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
  best.trio.forEach((p, i) => {
    const tr = el("tr");
    const th = el("th");
    th.textContent = shortName(p.name);
    th.title = `${p.name} (${fmtRating(p.rating)})`;
    tr.append(th);
    best.grid[i].forEach((prob) => {
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

function alternatives(rest) {
  const box = el("div", "alts");
  const h = el("p", "hint");
  h.textContent = "Next best trios";
  box.append(h);
  rest.forEach((r) => {
    const row = el("div", "alt");
    const nm = el("span", "nm");
    nm.textContent = r.trio.map((p) => p.name).join(", ");
    const sc = el("span", "sc");
    sc.textContent = `${fmtScore(r.expectedWins)} · ${fmtChance(r.winProb)}`;
    row.append(nm, sc);
    box.append(row);
  });
  return box;
}

function squadCard(team, side, title) {
  const card = el("div", "card");
  const h = el("h2");
  h.textContent = team.name;
  const hint = el("p", "hint");
  hint.textContent = title;
  card.append(h, hint);

  const box = el("div", "squad");
  squadFor(team).forEach((p) => {
    const label = el("label");
    const box2 = el("input");
    box2.type = "checkbox";
    box2.checked = !state.benched[side].has(p.id);
    if (!box2.checked) label.classList.add("out");
    box2.onchange = () => {
      if (box2.checked) state.benched[side].delete(p.id);
      else state.benched[side].add(p.id);
      renderLineup();
    };
    const nm = el("span", "nm");
    nm.textContent = p.name + (p.reliable ? "" : " *");
    const rt = el("span", "rt");
    rt.textContent = `${fmtRating(p.rating)} · ${p.appearances} app`;
    label.append(box2, nm, rt);
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
    action.textContent = "Plan a lineup for this team";
    action.onclick = () => {
      state.us = t.name;
      $("#pick-us").value = t.name;
      state.benched.us = new Set();
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
    state.benched.us = new Set();
    renderLineup();
  }, 150);

  $("#pick-them").oninput = debounce((e) => {
    state.them = e.target.value;
    state.benched.them = new Set();
    renderLineup();
  }, 150);

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
