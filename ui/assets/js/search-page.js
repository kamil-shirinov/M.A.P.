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
import { mountRosette } from "./ui/rosette.js";
import { createModeController, mountDoor } from "./ui/front-door.js";

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
let mode;

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

/** The index is requested on the FIRST keystroke, never at boot, and the
    keystroke that requested it does not wait for it.

    It used to. The handler awaited symbols.json and then set the phase to ready
    — but by the time 864 KB lands that handler is usually several keystrokes
    stale and bails at the sequence check, so nothing repainted: the chip stayed
    on "fetching" with the index open, and a term with no corpus hit kept saying
    absence was not yet knowable. "ZZQ" typed faster than the file arrived left
    it there until the next keystroke. So when the file lands, the query in the box NOW
    is re-run, whichever keystroke asked for the file.

    It also painted before grouping, so the first keystroke showed "No corpus
    company matches" for a term with corpus hits while the index was fetched. */
function requestIndex() {
  state.phase = "fetching";
  source.searchSymbols("", { limit: 1 }).then(({ indexSize }) => {
    state.symbolCount = indexSize ?? null;
    state.phase = "ready";
    onQuery(state.query);
  });
}

async function onQuery(value) {
  state.query = value;
  const term = value.trim().toUpperCase();
  const mine = ++state.seq;

  if (!term) {
    state.groups = {};
    state.matched = 0;
    paint();
    return;
  }

  if (state.phase === "cold") requestIndex();

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
  /* Last, and here rather than at the end of onQuery. A view transition
     snapshots the page as it stands when the mode flips, so the flip follows
     the render or the door morphs into the previous query's rows. And every
     path out of onQuery that changes the screen comes through paint, including
     the empty box — which is the way back to the door, and which an early
     return skipped when the call sat at the end of the handler. */
  mode.sync(state.query);
}

async function boot() {
  // The ground carries no data, so it does not wait for any.
  mountRosette($("ground"));

  const [exportState, companies] = await Promise.all([
    source.getExportState(),
    source.listCorpusCompanies(),
  ]);

  if (exportState.state === source.NO_EXPORT) {
    /* No door without an export: there is nothing to search. And door mode
       hides the page this state is written into, which left a blank screen. */
    document.body.dataset.mode = "open";
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
  const door = mountDoor($("door"), {
    onQuery,
    companies: state.corpus.length,
    runsBySource: source.runCountsBySource(exportState.manifest),
    finding: source.devScoringRecordExported(exportState.manifest),
  });
  mode = createModeController({ doorInput: door.input, pageInput: box.input });

  /* Home is the empty box, reached the way clearing reaches it. Through onQuery
     rather than straight to the mode controller: a query still in flight would
     otherwise land afterwards, repaint, and reopen the page with its term back
     in the box. A modified click still opens index.html the ordinary way. */
  document.querySelector(".masthead h1 a").addEventListener("click", (event) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    onQuery("");
  });

  paint();
  mode.focus();
}

boot();
