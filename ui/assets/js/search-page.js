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
import { renderFunnel, whyGroups } from "./ui/search-funnel.js";
import { renderPageWhy } from "./ui/page-why.js";
import { renderFooter, renderMastheadVintage } from "./ui/company-footer.js";
import { applyPageProvenance, enforce } from "./lib/provenance-audit.js";
import { mountPageRosette } from "./ui/rosette.js";
import { createModeController, mountDoor, mountMastheadNav } from "./ui/front-door.js";
import { renderNoExport } from "./ui/no-export.js";

const $ = (id) => document.getElementById(id);

/* THE QUERY LIVES IN THE URL, as `?q=`. The box mirrors it rather than owning it,
   which is what makes the three ways back to a result behave the same way: the
   nav link, the back button and a reload all just re-read `?q=`.

   Keystrokes REPLACE the entry rather than pushing one. Pushing per keystroke
   would bury the page you arrived from under one entry per letter, so "apple"
   typed then left would need five presses of Back to escape. The crest pushes,
   because going home is the one in-page move worth being able to undo — and it
   is what "back keeps the search" means in practice.

   Cross-document transitions are already on (`@view-transition { navigation:
   auto }`), so arriving at `?q=apple` from a company page animates; within the
   document `mode.sync` owns the flip and animates it the same way. */
const QUERY_PARAM = "q";

function queryFromLocation() {
  try {
    return new URL(window.location.href).searchParams.get(QUERY_PARAM) ?? "";
  } catch {
    return ""; // no URL to read: a file:// engine without searchParams, or a stub
  }
}

function writeQueryToLocation(query, push = false) {
  if (!window.history?.replaceState) return;
  let url;
  try {
    url = new URL(window.location.href);
  } catch {
    return;
  }
  const term = query.trim();
  if (term) url.searchParams.set(QUERY_PARAM, term);
  else url.searchParams.delete(QUERY_PARAM);
  const next = url.pathname + url.search + url.hash;
  // An identical URL is not pushed. Otherwise the crest, clicked twice on an
  // already-empty box, would stack entries that do nothing when visited.
  if (next === window.location.pathname + window.location.search + window.location.hash) return;
  if (push) window.history.pushState({ [QUERY_PARAM]: term }, "", next);
  else window.history.replaceState({ [QUERY_PARAM]: term }, "", next);
}

/* The one move that earns a history entry. Named, so the click handler reads as
   what it does and the entry cannot be pushed by accident from anywhere else. */
const pushQueryToLocation = (query) => writeQueryToLocation(query, true);

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
  // The export's counted funnel, read once at boot. Null on an export written
  // before `map export` counted one.
  funnel: null,
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
  // The boundary's rule, not a second copy of it: two copies would let the two
  // lists disagree about what matched, which is what the count reconciles.
  return state.corpus.filter((row) => source.matchesTerm(row, term)).sort(orderFor(term));
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
  const { rows } = await source.searchSymbols(term, { limit: Infinity });
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

  // The union of the two lists, keyed on ticker. See `countMatches`.
  return {
    groups,
    matched: source.countMatches(rows, corpus),
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
  // The counter beside the box reports the query, not the file: `matched` is
  // null until something is typed, so an empty box shows no count at all.
  box.update({ phase: state.phase, matched: state.query.trim() ? state.matched : null });
  renderResults($("results"), {
    phase: state.phase,
    query: state.query,
    groups: state.groups,
    matched: state.matched,
  });
  renderFunnel($("funnel"), { symbolCount: state.symbolCount, funnel: state.funnel });
  applyPageProvenance();
  enforce();
  /* Last, and here rather than at the end of onQuery. A view transition
     snapshots the page as it stands when the mode flips, so the flip follows
     the render or the door morphs into the previous query's rows. And every
     path out of onQuery that changes the screen comes through paint, including
     the empty box — which is the way back to the door, and which an early
     return skipped when the call sat at the end of the handler. */
  /* Before the flip, and from paint rather than from onQuery, for the same reason
     the flip is here: every path that changes the screen comes through paint, and
     the URL is part of the screen. Before rather than after because the URL is not
     rendered, so it is not in the transition's snapshot, and `mode.sync` has to
     stay the last thing a paint does. */
  writeQueryToLocation(state.query);
  mode.sync(state.query);
}

async function boot() {
  // The ground carries no data, so it does not wait for any.
  mountPageRosette($("ground"));

  const [exportState, companies] = await Promise.all([
    source.getExportState(),
    source.listCorpusCompanies(),
  ]);

  if (exportState.state === source.NO_EXPORT) {
    /* No door without an export: there is nothing to search. And door mode
       hides the page this state is written into, which left a blank screen. */
    document.body.dataset.mode = "open";
    renderNoExport($("search-page"), exportState.why, {
      footer: $("footer"), vintage: $("masthead-vintage"),
    });
    return;
  }

  state.corpus = companies.rows;

  renderMastheadVintage($("masthead-vintage"), exportState.manifest);
  renderFooter($("footer"), exportState.manifest);
  state.funnel = exportState.manifest?.funnel ?? null;
  renderPageWhy($("why"), { groups: whyGroups(state.funnel) });

  mountMastheadNav($("masthead-nav"), { current: "search" });
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
    // Pushed before the repaint, so the entry Back returns to is the query that
    // was on screen and not the empty box that replaces it.
    pushQueryToLocation("");
    onQuery("");
  });

  /* Back and forward within the document. Only the crest pushes, so this fires
     for that one move — but it also catches a forward press and an entry restored
     from the session, and going through onQuery means the rows are rebuilt rather
     than assumed to still match the URL. */
  window.addEventListener("popstate", () => {
    onQuery(queryFromLocation());
  });

  /* An arriving `?q=` is a query typed on some earlier visit, so it goes through
     onQuery exactly as a keystroke does — including the index request, which a
     seeded query needs as much as a typed one. `mode.sync` inside that paint
     opens the page, so a link to `?q=apple` lands on results and not the door. */
  const seeded = queryFromLocation();
  if (seeded) {
    box.input.value = seeded;
    await onQuery(seeded);
  } else {
    paint();
  }
  mode.focus();
}

boot();
