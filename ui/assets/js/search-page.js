/* Composition root for the search screen.

   THE SCREEN'S JOB is to turn a typed symbol into one of four answers, only one
   of which has a destination. It does not forecast anything and cannot: there is
   no server behind these files.

   WHAT LOADS WHEN, which is most of the design:
     boot            universe.json, 7.5 KB — the 120 corpus companies.
     first corpus hit corpus.json, 108.8 KB — the filing and run counts a corpus
                     row shows. NOT at boot: universe.json carries ticker, name
                     and split only, and the counts are worth 108.8 KB exactly
                     when a row that displays them exists.
     first keystroke symbols.json, 864 KB — the full index.
     first hit that
     falls outside
     the corpus      filers.json, 1.2 MB — the Item 2.02 pre-screen.

   So the cold box is not dead: a corpus company resolves before the index is
   requested, and a row outside the corpus cannot be shown at all until it is. */

import * as source from "./data/source.js";
import { mountBox, renderResults } from "./ui/search-box.js";
import { renderFunnel, renderWhy } from "./ui/search-funnel.js";
import { renderFooter, renderMastheadVintage } from "./ui/company-footer.js";
import { applyPageProvenance, enforce } from "./lib/provenance-audit.js";

const $ = (id) => document.getElementById(id);

/* How many matches get the filer pre-screen. A screen is a scan of filers.json
   per ticker (the data boundary offers no ticker -> filer map), and group
   membership is not known until a row is screened, so the cap is on screening
   and the total match count is reported separately rather than implied. */
const SCREEN_CAP = 24;

const state = {
  phase: "cold",
  query: "",
  corpus: [],
  symbolCount: null,
  matched: 0,
  screened: 0,
  groups: {},
  counts: null,
  seq: 0,
};

let box;

function orderFor(term) {
  return (a, b) => {
    if (a.ticker === term) return -1;
    if (b.ticker === term) return 1;
    return a.ticker.localeCompare(b.ticker);
  };
}

/** Corpus matches come from the 7.5 KB file in memory, so they resolve in every
    phase — including before the index has been requested. */
function corpusMatches(term) {
  return state.corpus
    .filter((row) => {
      const name = source.isAbsent(row.name) ? "" : row.name;
      return row.ticker.startsWith(term) || name.toUpperCase().includes(term);
    })
    .sort(orderFor(term));
}

async function group(term) {
  const hits = corpusMatches(term);
  if (hits.length && !state.counts) state.counts = await source.getCorpusFilingCounts();
  const corpus = hits.map((row) => ({
    ...row,
    filings: state.counts?.get(row.ticker)?.filings ?? 0,
    runs: state.counts?.get(row.ticker)?.runs ?? 0,
  }));
  const groups = { corpus, earnings: [], none: [], unfiled: [] };

  if (state.phase !== "ready") return { groups, matched: corpus.length, screened: corpus.length };

  const held = new Set(state.corpus.map((r) => r.ticker));
  const { rows, matched } = await source.searchSymbols(term, { limit: Infinity });
  const outside = rows.filter((r) => !held.has(r.ticker)).sort(orderFor(term));
  const slice = outside.slice(0, SCREEN_CAP);

  const screens = await Promise.all(slice.map((r) => source.getFilerScreen(r.ticker)));
  slice.forEach((row, i) => {
    const screen = screens[i];
    const entry = { ticker: row.ticker, name: row.name, exchange: row.exchange ?? null, screen };
    if (source.isAbsent(screen)) groups.unfiled.push(entry);
    else if (screen.item_202_in_recent) groups.earnings.push(entry);
    else groups.none.push(entry);
  });

  return {
    groups,
    matched: (matched ?? rows.length) + corpus.length - 0,
    screened: corpus.length + slice.length,
  };
}

async function onQuery(value) {
  state.query = value;
  const term = value.trim().toUpperCase();
  const mine = ++state.seq;

  // The index is requested on the FIRST keystroke, never at boot.
  if (state.phase === "cold" && term) {
    state.phase = "fetching";
    paint();
    const { indexSize } = await source.searchSymbols(term, { limit: 1 });
    if (mine !== state.seq && state.phase === "fetching") { /* keep going: the file is shared */ }
    state.symbolCount = indexSize ?? null;
    state.phase = "ready";
  }

  if (!term) {
    state.groups = {};
    state.matched = 0;
    paint();
    return;
  }

  const { groups, matched, screened } = await group(term);
  if (mine !== state.seq) return; // a later keystroke owns the screen
  state.groups = groups;
  state.matched = matched;
  state.screened = screened;
  paint();
}

function paint() {
  box.update({ phase: state.phase, searchable: state.phase === "ready" ? state.symbolCount : state.corpus.length });
  renderResults($("results"), {
    phase: state.phase,
    query: state.query,
    groups: state.groups,
    matched: state.matched,
  });
  renderFunnel($("funnel"), { symbolCount: state.symbolCount });
  applyPageProvenance();
  enforce();
}

async function boot() {
  const [exportState, companies] = await Promise.all([
    source.getExportState(),
    source.listCorpusCompanies(),
  ]);

  if (exportState.state === source.NO_EXPORT) {
    const main = $("search-page");
    main.textContent = "";
    const box2 = document.createElement("div");
    box2.className = "cmp-empty";
    box2.dataset.chrome = "no export is present; nothing on screen is a figure";
    const h = document.createElement("h1");
    h.textContent = "No export";
    const p = document.createElement("p");
    p.textContent = exportState.why.why;
    const pre = document.createElement("pre");
    pre.textContent = exportState.why.remedy;
    box2.append(h, p, pre);
    main.append(box2);
    return;
  }

  state.corpus = companies.rows;

  renderMastheadVintage($("masthead-vintage"), exportState.manifest);
  renderFooter($("footer"), exportState.manifest);
  renderWhy($("why"));

  box = mountBox($("box"), { onQuery });
  paint();
  box.focus();
}

boot();
