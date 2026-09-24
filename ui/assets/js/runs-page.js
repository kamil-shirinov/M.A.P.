/* Composition root for the runs screen.

   WHAT LOADS WHEN. Each stage paints before the next arrives, and nothing on
   screen waits on the big file:

     manifest.json   1.9 KB  — the total, the four population counts and sizes,
                     the vintage stamps. The count comes from here, not from the
                     rows, so the header is true before the journal lands.
     universe.json   7.5 KB  } in parallel — names and splits for the rows, and
     corpus.json   108.8 KB  } the filings the corpus settled with no run.
     runs/by_source  649.2 KB — the journal itself, read as four files in SOURCES
                     order. While it is in flight the journal shows what it is
                     reading, not skeleton rows pretending to be data.

   This is the one screen that opens the run files. The front door counts runs
   from the manifest for exactly this reason.

   THE POOLING IS THE PAGE'S, NOT THE EXPORT'S. Four files, four counts, no
   total anywhere in the export; the header adds them and shows its arithmetic.
   `ledger.items_settled` is 709 and never appears here — it counts corpus items,
   including 8 that never ran, and this screen counts runs. */

import * as source from "./data/source.js";
import { applyPageProvenance, enforce } from "./lib/provenance-audit.js";
import { mountRosette } from "./ui/rosette.js";
import { mountMastheadNav } from "./ui/front-door.js";
import { renderFooter, renderMastheadVintage } from "./ui/company-footer.js";
import { renderDrift, renderIdentity, renderPopulations, renderUnrun } from "./ui/runs-header.js";
import { describeFilters, matches, quarterLabel, renderChart, renderFilters } from "./ui/runs-filters.js";
import { renderJournal } from "./ui/runs-journal.js";

const $ = (id) => document.getElementById(id);

/* Below this many matching runs, every group opens: a collapse that hides
   forty rows behind seven clicks is friction without a payoff. */
const OPEN_ALL_AT = 60;

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const state = {
  stage: "reading",
  error: null,
  manifest: null,
  counts: { corpus: 0, edgar: 0, news: 0, unknown: 0 },
  journal: null,
  rows: [],
  universe: new Map(),
  unrun: [],
  filters: { ticker: null, relation: "all", outcome: "all", freeze: "all" },
  query: "",
  openGroups: new Set(),
  openRows: new Set(),
};

/** Quarters, newest first, with the months inside them for the header. Totals
    come from every row so a filtered group can say "12 of 83". */
function group(filtered) {
  const totals = new Map();
  for (const r of state.rows) totals.set(quarterLabel(r.anchor_date), (totals.get(quarterLabel(r.anchor_date)) ?? 0) + 1);

  const groups = new Map();
  for (const r of filtered) {
    const label = quarterLabel(r.anchor_date);
    if (!groups.has(label)) groups.set(label, []);
    groups.get(label).push(r);
  }
  return [...groups.entries()]
    .sort((a, b) => (a[0] < b[0] ? 1 : -1))
    .map(([label, rows]) => {
      const months = new Map();
      for (const r of rows) {
        const key = MONTHS[Number(r.anchor_date.slice(5, 7)) - 1];
        months.set(key, (months.get(key) ?? 0) + 1);
      }
      return {
        label,
        rows,
        total: totals.get(label) ?? rows.length,
        months: [...months.entries()],
        dates: new Set(rows.map((r) => r.anchor_date)).size,
        open: rows.filter((r) => source.isAbsent(r.outcome)).length,
        drift: rows.filter((r) => !source.isAbsent(r.anchor_drift)).length,
      };
    });
}

const spanOf = (values) => ({ min: Math.min(...values), max: Math.max(...values) });

/** Whenever a filter moves, the open set is recomputed rather than kept: a
    group that no longer matches should not stay open behind the scenes. */
function resetOpenGroups(filtered, groups) {
  state.openGroups = new Set(
    filtered.length <= OPEN_ALL_AT ? groups.map((g) => g.label) : groups.slice(0, 1).map((g) => g.label),
  );
}

function paint() {
  const filtered = state.rows.filter((r) => matches(r, state.filters));

  renderIdentity($("runs-identity"), { rows: state.rows, counts: state.counts, universe: state.universe });
  renderPopulations($("populations"), { manifest: state.manifest, journal: state.journal, counts: state.counts });
  if (state.unrun.length) renderUnrun($("unrun"), { filings: state.unrun });
  if (state.rows.length) {
    renderDrift($("drift"), {
      rows: state.rows,
      total: state.rows.length,
      selected: state.filters.ticker,
      onSelect: (ticker) => set({ ticker }),
    });
  }

  const groups = state.stage === "ready" ? group(filtered) : [];
  const hosts = renderJournal($("journal"), {
    state: state.stage,
    error: state.error,
    readingSize: state.manifest?.files?.["runs/by_source/unknown.json"],
    rows: state.rows,
    filtered,
    groups,
    allOpen: filtered.length <= OPEN_ALL_AT,
    span: groups.length ? spanOf(groups.map((g) => g.total)) : { min: 0, max: 0 },
    monthSpan: monthSpan(),
    describe: describeFilters(state.filters, state.universe),
    openGroups: state.openGroups,
    openRows: state.openRows,
    universe: state.universe,
    onToggleGroup: (label) => {
      if (state.openGroups.has(label)) state.openGroups.delete(label);
      else state.openGroups.add(label);
      paint();
    },
    onToggleRow: (runId) => {
      // Keyed on run_id, never on index: filtering and regrouping reorder freely.
      if (state.openRows.has(runId)) state.openRows.delete(runId);
      else state.openRows.add(runId);
      paint();
    },
  });

  if (state.stage === "ready") {
    renderFilters(hosts.filters, {
      rows: state.rows,
      filtered,
      filters: state.filters,
      query: state.query,
      universe: state.universe,
      on: {
        ticker: (ticker) => set({ ticker }),
        relation: (relation) => set({ relation }),
        outcome: (outcome) => set({ outcome }),
        freeze: (freeze) => set({ freeze }),
        query: (q) => { state.query = q; paint(); },
        clear: () => set({ ticker: null, relation: "all", outcome: "all", freeze: "all" }),
      },
    });
    renderChart(hosts.chart, {
      rows: state.rows,
      filtered,
      filtering: describeFilters(state.filters, state.universe).length > 0,
      onPick: (label) => {
        state.openGroups = new Set([label]);
        paint();
        document.getElementById(`q-${label.replace(/\s+/g, "-")}`)?.scrollIntoView({ block: "start" });
        window.scrollBy(0, -40);
      },
    });
  }

  applyPageProvenance();
  enforce();
}

function monthSpan() {
  if (!state.rows.length) return { min: 0, max: 0 };
  const months = new Map();
  for (const r of state.rows) {
    const key = r.anchor_date.slice(0, 7);
    months.set(key, (months.get(key) ?? 0) + 1);
  }
  return spanOf([...months.values()]);
}

/** Every filter change goes through here, so the open-group reset cannot be
    forgotten at one call site. Open ROWS survive: they are keyed on run_id and
    a row that comes back should come back as the reader left it. */
function set(patch) {
  Object.assign(state.filters, patch);
  if (patch.ticker !== undefined) state.query = "";
  const filtered = state.rows.filter((r) => matches(r, state.filters));
  resetOpenGroups(filtered, group(filtered));
  paint();
}

async function boot() {
  mountRosette($("ground"));
  mountMastheadNav($("masthead-nav"), { current: "runs" });

  // -- stage 1: the manifest
  const exportState = await source.getExportState();
  if (exportState.state === source.NO_EXPORT) {
    state.stage = "no-export";
    state.error = exportState.why;
    paint();
    return;
  }
  state.manifest = exportState.manifest;
  const counts = source.runCountsBySource(state.manifest);
  if (!source.isAbsent(counts)) {
    for (const name of source.SOURCES) state.counts[name] = counts[name].value;
  }
  renderMastheadVintage($("masthead-vintage"), state.manifest);
  renderFooter($("footer"), state.manifest);
  paint();

  // -- stage 2: names, splits, and the filings that never ran
  const [companies, unrun] = await Promise.all([
    source.listCorpusCompanies(),
    source.listUnrunFilings(),
  ]);
  state.universe = new Map(companies.rows.map((r) => [r.ticker, r]));
  state.unrun = unrun;
  paint();

  // -- stage 3: the journal, 649.2 KB
  try {
    state.journal = await source.listJournal();
  } catch (err) {
    state.stage = "failed";
    state.error = String(err.message ?? err);
    paint();
    return;
  }
  // Concatenated HERE by looping the four sources, the same way the company page
  // does it. There is no combined array at the boundary to flatten by accident.
  const rows = [];
  for (const name of source.SOURCES) rows.push(...state.journal.bySource[name]);
  state.rows = rows;
  state.stage = "ready";
  resetOpenGroups(rows, group(rows));
  paint();
}

boot();
