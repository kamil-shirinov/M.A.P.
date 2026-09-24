/* Filters and the month chart.

   All filtering is client-side: there is no server behind these files, and the
   whole journal is already in memory once it lands.

   COUNTS ARE CROSS-FILTERED. The number on an option is what choosing THAT
   option would show given the other three axes — not how many rows carry the
   value overall. The two differ whenever another filter is active, and the
   second is the one that lies: it promises rows a click then does not produce.

   A zero-count option is shown disabled, never hidden. "No run in this export
   has this value" is a fact about the corpus; an option that vanishes leaves the
   reader to guess whether they mis-clicked or the state does not exist. */

import { chromeText, derive, renderFigure } from "../lib/figure.js";
import { isAbsent } from "../data/source.js";

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

export const RELATIONS = [
  ["all", "all"],
  ["ledger_item", "panel item"],
  ["repeat_of_exhibit", "repeat"],
  ["outside_corpus", "outside corpus"],
  ["unchecked", "not compared"],
];

export const OUTCOMES = [
  ["all", "all"],
  ["closed", "closed"],
  ["window_open", "window open"],
  ["absent_from_snapshot", "absent from snapshot"],
  ["not_requested", "not requested"],
];

export const freezeKey = (row) => (isAbsent(row.freeze_version) ? "unrecorded" : row.freeze_version);

/** One row against one filter set. The only place membership is decided. */
export function matches(row, f) {
  if (f.ticker && row.ticker !== f.ticker) return false;
  if (f.relation !== "all" && row.corpus_relation !== f.relation) return false;
  if (f.outcome !== "all" && row.outcome_status !== f.outcome) return false;
  if (f.freeze !== "all" && freezeKey(row) !== f.freeze) return false;
  return true;
}

/** Versions present in the data, newest first, then the absence. Never a
    hardcoded list: a re-export with a new freeze would silently lose a filter. */
export function freezeOptions(rows) {
  const versions = [...new Set(rows.map(freezeKey))];
  const real = versions.filter((v) => v !== "unrecorded").sort().reverse();
  return [["all", "all"], ...real.map((v) => [v, v]), ...(versions.includes("unrecorded") ? [["unrecorded", "unrecorded"]] : [])];
}

const countWith = (rows, f, axis, value) => rows.reduce((n, r) => n + (matches(r, { ...f, [axis]: value }) ? 1 : 0), 0);

export function renderFilters(root, { rows, filtered, filters, query, universe, on }) {
  root.textContent = "";
  const dl = el("dl", "runs-filters");

  const row = (label, fill) => {
    dl.append(el("dt", null, label));
    const dd = el("dd");
    fill(dd);
    dl.append(dd);
  };

  // ---- ticker: free text over the universe, or a chip once chosen ----
  row("Ticker", (dd) => {
    if (filters.ticker) {
      const chip = el("span", "runs-chip");
      chip.append(el("span", "t", filters.ticker));
      const name = universe.get(filters.ticker)?.name;
      // A company name can hold digits — Phillips 66 — so it is chrome, not text.
      if (name && !isAbsent(name)) chip.append(chromeText(name, "a company name, which can contain digits"));
      const link = el("a", null, "company page");
      link.href = `company.html?ticker=${encodeURIComponent(filters.ticker)}`;
      chip.append(link);
      const x = el("button", null, "×");
      x.type = "button";
      x.title = "Clear the ticker filter";
      x.addEventListener("click", () => on.ticker(null));
      chip.append(x);
      dd.append(chip);
      return;
    }
    const box = el("div", "runs-tickerbox");
    const input = document.createElement("input");
    input.type = "search";
    input.value = query;
    input.placeholder = "ticker or name";
    input.spellcheck = false;
    input.setAttribute("aria-label", "Filter by ticker or company name");
    input.addEventListener("input", () => on.query(input.value));
    box.append(input);
    dd.append(box);

    const term = query.trim().toUpperCase();
    if (term) {
      // Only the suggestions depend on the query: nothing about the 779 rows
      // re-renders while someone types.
      const hits = [...universe.entries()]
        .filter(([t, u]) => t.startsWith(term) || String(isAbsent(u.name) ? "" : u.name).toUpperCase().includes(term))
        .slice(0, 10);
      for (const [t] of hits) {
        const b = el("button", "runs-opt runs-opt--mono");
        b.type = "button";
        b.append(document.createTextNode(t));
        const n = countWith(rows, filters, "ticker", t);
        const s = el("span", "n");
        s.append(renderFigure(derive(n, "int")));
        b.append(s);
        b.disabled = n === 0;
        if (n === 0) b.title = "No run in this export has this value";
        b.addEventListener("click", () => on.ticker(t));
        dd.append(b);
      }
    } else {
      dd.append(el("span", "runs-note", ""), chromeText("120 tickers, 4 to 16 runs each", "the shape of the journal, counted from the rows"));
    }
  });

  const axis = (label, key, options, note) => row(label, (dd) => {
    for (const [value, text] of options) {
      const b = el("button", key === "freeze" && value !== "all" ? "runs-opt runs-opt--mono" : "runs-opt");
      b.type = "button";
      // A version is digits. Marked, not left as a text node the audit must guess at.
      b.append(key === "freeze" && value !== "all" && value !== "unrecorded"
        ? chromeText(text, "a frozen corpus version")
        : document.createTextNode(text));
      const n = countWith(rows, filters, key, value);
      const s = el("span", "n");
      s.append(renderFigure(derive(n, "int")));
      b.append(s);
      const active = filters[key] === value;
      b.setAttribute("aria-pressed", String(active));
      // An ACTIVE option is never disabled: the way out of a zero result is the
      // control that produced it.
      b.disabled = n === 0 && !active;
      if (b.disabled) b.title = "No run in this export has this value";
      b.addEventListener("click", () => on[key](value));
      dd.append(b);
    }
    dd.append(el("span", "runs-note", note));
  });

  axis("Relation", "relation", RELATIONS, "relation to the frozen corpus");
  axis("Outcome", "outcome", OUTCOMES, "four states in the contract, two occur");
  axis("Freeze", "freeze", freezeOptions(rows), "the frozen corpus the run executed under");
  root.append(dl);

  // ---- the summary, and the only way to clear everything at once ----
  const parts = describeFilters(filters, universe);
  const p = el("p", "runs-summary");
  if (parts.length) {
    p.append(renderFigure(derive(filtered.length, "int")));
    p.append(chromeText(filtered.length === 1 ? " run matches " : " runs match ", "rows the current filters show"));
    p.append(chromeText(parts.join(" · "), "the filters currently applied"));
    p.append(document.createTextNode(" — counts on each control are what that choice would show, given the others."));
    const clear = el("a", null, "clear filters");
    clear.href = "#";
    clear.addEventListener("click", (e) => { e.preventDefault(); on.clear(); });
    p.append(clear);
  } else {
    p.append(document.createTextNode(
      "No filter. Counts on each control are what that choice would show, given the others."));
  }
  root.append(p);
}

export function describeFilters(filters, universe) {
  const out = [];
  if (filters.ticker) out.push(filters.ticker);
  if (filters.relation !== "all") out.push(RELATIONS.find(([v]) => v === filters.relation)[1]);
  if (filters.outcome !== "all") out.push(OUTCOMES.find(([v]) => v === filters.outcome)[1]);
  if (filters.freeze !== "all") out.push(`freeze ${filters.freeze}`);
  return out;
}

const MONTH_INITIAL = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"];

/** Twenty bars, one per anchor month. Height is every run that month; the fill
    is the share that matches. Earnings season is the shape, and the stub-and-wall
    range (3 to 97) is why the table below groups by quarter and not by month. */
export function renderChart(root, { rows, filtered, filtering, onPick }) {
  root.textContent = "";
  const all = tally(rows.map((r) => r.anchor_date.slice(0, 7)));
  const hit = tally(filtered.map((r) => r.anchor_date.slice(0, 7)));
  const drift = new Set(rows.filter((r) => !isAbsent(r.anchor_drift)).map((r) => r.anchor_date.slice(0, 7)));
  const months = [...all.keys()].sort();
  const max = Math.max(...all.values());

  const note = el("p", "runs-note",
    filtering
      ? "bar height is every run that month; blue is the share that matches · red dot marks a re-based run"
      : "earnings season is the shape · red dot marks a month holding a re-based run · select a bar to open its group");
  root.append(note);

  const chart = el("div", "runs-chart");
  for (const [i, month] of months.entries()) {
    const total = all.get(month);
    const matched = hit.get(month) ?? 0;
    const quarterStart = i === 0 || Number(month.slice(5, 7)) % 3 === 1;
    const b = el("button", "runs-bar");
    b.type = "button";
    b.dataset.matched = String(filtering && matched > 0);
    b.dataset.quarter = String(quarterStart);
    b.disabled = matched === 0;

    const n = el("span", "runs-bar-n");
    if (matched > 0 || !filtering) n.append(renderFigure(derive(filtering ? matched : total, "int")));
    b.append(n);

    const col = el("div", "runs-bar-col");
    col.style.height = `${Math.max(2, Math.round((total / max) * 72))}px`;
    const fill = el("div", "runs-bar-fill");
    fill.style.height = `${Math.round((matched / total) * 100)}%`;
    col.append(fill);
    b.append(col);

    const lab = el("span", "runs-bar-lab");
    lab.append(chromeText(MONTH_INITIAL[Number(month.slice(5, 7)) - 1], "the month this bar counts"));
    if (drift.has(month)) lab.append(el("span", "runs-bar-dot", "•"));
    if (quarterStart) {
      lab.append(document.createElement("br"));
      lab.append(chromeText(quarterLabel(month), "the quarter this bar opens"));
    }
    b.append(lab);
    b.addEventListener("click", () => onPick(quarterLabel(month)));
    chart.append(b);
  }
  root.append(chart);
}

export const quarterLabel = (iso) => `${iso.slice(0, 4)} Q${Math.floor((Number(iso.slice(5, 7)) - 1) / 3) + 1}`;

function tally(values) {
  const m = new Map();
  for (const v of values) m.set(v, (m.get(v) ?? 0) + 1);
  return m;
}
