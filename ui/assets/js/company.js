/* Composition root for the company page — one page per company.

   TWO KINDS OF PAGE, ONE URL. A corpus company (120 of them) has a record: its
   frozen filings, the runs the ledger maps to them, the scoring. Any other filer
   that publishes earnings has no record here, and its page says so rather than
   showing an empty one. Both end with the same last section, "Live runs, outside
   the record", where a run is started and watched (ADR 0036, amendment of
   2026-09-30).

   The `example` parameter picks a corpus company for review. Three exist because
   the distinctive states live on one or two companies each and must not drive the
   layout:

     typical  ACHC — six ledger runs, both bands, all closed, no drift.
     ati      ATI  — a repeat whose panel run does not exist.
     aapl     AAPL — outside-corpus runs, an open window, and drift. */

import * as source from "./data/source.js";
import { renderFilerIdentity, renderIdentity } from "./ui/company-identity.js";
import { renderSeries } from "./ui/company-series.js";
import { renderFilings } from "./ui/company-filings.js";
import { renderRuns } from "./ui/company-runs.js";
import { renderScoring } from "./ui/company-scoring.js";
import { renderFooter, renderMastheadVintage } from "./ui/company-footer.js";
import { mountPageRosette } from "./ui/rosette.js";
import { liveRows, renderLive } from "./ui/company-live.js";
import { noServerNotes } from "./ui/analyse-offer.js";
import { fetchPrices, serverPresent } from "./data/server.js";
import { renderPageWhy } from "./ui/page-why.js";
import { COMPANY_WHY, LIVE_WHY } from "./ui/company-why.js";
import { applyPageProvenance, enforce } from "./lib/provenance-audit.js";
import { mountMastheadNav } from "./ui/front-door.js";
import { renderNoExport } from "./ui/no-export.js";

const EXAMPLES = { typical: "ACHC", ati: "ATI", aapl: "AAPL" };

const $ = (id) => document.getElementById(id);

/** Disclosure state, keyed on RUN ID and never on row index.

    An anchor can repeat within a company — ATI has two runs whose anchors sit a
    day apart, and a paginated or filtered ledger reorders freely — so an
    index-keyed open row follows the position rather than the run. */
const open = new Set();

/** Two ways in, and they are not the same thing.

    ?ticker=  a link from search, the runs screen or an old analyse link. Any
              company in the symbol index — and any string at all, since a URL
              can be typed. `horizon` travels with it from an old analyse link
              and preselects the control; it never starts a run.
    ?example= the review form: one of three corpus names.

    `body[data-example]` reads "linked" for a ticker link rather than an example
    name, so styling keyed on an example cannot silently apply to an arbitrary
    company. */
function target() {
  const params = new URLSearchParams(location.search);
  const horizon = Number(params.get("horizon")) || null;
  const linked = params.get("ticker");
  if (linked && linked.trim()) {
    return { mode: "linked", ticker: linked.trim().toUpperCase(), horizon };
  }
  const asked = params.get("example") ?? "typical";
  const mode = EXAMPLES[asked] ? asked : "typical";
  return { mode, ticker: EXAMPLES[mode], horizon };
}

/** The record's runs and the live runs, as two objects that never meet.

    The record keeps all four keys so the components that iterate SOURCES still
    can; the live keys are simply empty in it. */
function split(runs) {
  const record = { bySource: {}, provenance: runs.provenance };
  for (const name of source.SOURCES) {
    record.bySource[name] = source.RECORD_SOURCES.includes(name) ? runs.bySource[name] : [];
  }
  const live = source.LIVE_SOURCES.flatMap((name) => runs.bySource[name]);
  return { record, live };
}

async function paint() {
  const { mode, ticker, horizon } = target();
  document.body.dataset.example = mode;

  const state = await source.getExportState();
  if (state.state === source.NO_EXPORT) {
    showNoExport(state);
    return;
  }
  renderMastheadVintage($("masthead-vintage"), state.manifest);
  renderFooter($("footer"), state.manifest);

  const [company, runs, replay] = await Promise.all([
    source.getCompany(ticker),
    source.listRuns(ticker),
    source.getReplay(),
  ]);
  const { record, live: exported } = split(runs);
  const live = await liveRows(ticker, exported);

  let recount;
  if (!source.isAbsent(company)) {
    recount = await paintRecord(company, record, live);
  } else {
    const filer = await source.getFiler(ticker);
    const readable = !source.isAbsent(filer)
      && !source.isAbsent(filer.screen) && filer.screen.item_202_in_recent;
    if (!readable) {
      renderUnknownCompany(ticker, company, filer, state.manifest);
      return;
    }
    recount = await paintFiler(filer, record, live);
  }

  await renderLive($("live"), {
    ticker,
    name: source.isAbsent(company) ? null : company.name,
    rows: live,
    inCorpus: !source.isAbsent(company),
    replay,
    horizon,
    onRows: recount,
  });
  if (location.hash === "#live") $("live").scrollIntoView?.({ block: "start" });

  renderPageWhy($("why"), {
    groups: [...COMPANY_WHY, ...LIVE_WHY, ...((await serverPresent()) ? [] : [noServerNotes()])],
  });
  applyPageProvenance();
  enforce();
}

/** A corpus company: the record, then the live section. */
async function paintRecord(company, record, live) {
  const [series, scoring] = await Promise.all([
    source.getPriceSeries(company.ticker),
    source.listScoringRecords(),
  ]);
  renderTitle(company);
  const identity = (rows) =>
    renderIdentity($("identity"), { company, runs: record, liveRuns: rows.length });
  identity(live);
  renderSeries($("series"), { series, runs: record });
  renderFilings($("filings"), { company, runs: record });
  paintRuns(company, record);
  renderScoring($("scoring"), { scoring, company });
  // After a run, the live count follows the list; nothing in the record moves.
  return (rows) => { identity(rows); applyPageProvenance(); enforce(); };
}

/** Only the table repaints when a row opens. Repainting the page would also
    rebuild the live section — and wipe a run that is streaming into it. */
function paintRuns(company, record) {
  renderRuns($("runs"), {
    runs: record,
    company,
    open,
    onToggle: (runId) => {
      // Keyed on run_id. See `open` above.
      if (open.has(runId)) open.delete(runId);
      else open.add(runId);
      paintRuns(company, record);
      applyPageProvenance();
      enforce();
    },
  });
}

/** A filer outside the corpus: identity, a price series if a server can fetch
    one, and the live section. The record's three sections are removed rather
    than left empty, because there is no record to be empty. */
async function paintFiler(filer, record, live) {
  renderFilerTitle(filer);
  const earlier = source.RECORD_SOURCES.reduce((n, name) => n + record.bySource[name].length, 0);
  const identity = (rows) =>
    renderFilerIdentity($("identity"), { filer, liveRuns: rows.length, earlierRuns: earlier });
  identity(live);
  const series = (await serverPresent())
    ? await fetchPrices(filer.ticker)
    : source.absent(
      source.NOT_COMPUTED,
      `No price history on this copy. ${filer.ticker} is outside the frozen corpus, so the ` +
        "export carries no series for it, and there is no server behind these files to fetch one.",
    );
  const none = { bySource: Object.fromEntries(source.SOURCES.map((name) => [name, []])) };
  renderSeries($("series"), { series, runs: none, title: "Price series" });
  for (const id of ["filings", "runs", "scoring"]) $(id)?.remove();
  return (rows) => { identity(rows); applyPageProvenance(); enforce(); };
}

/** The one state the export cannot describe for itself: there is no manifest to
    read an absence from, so this module states it. Distinct from a partial
    export, which exists and names its own gaps. */
function showNoExport(state) {
  renderNoExport($("company"), state.why, {
    footer: $("footer"), vintage: $("masthead-vintage"),
  });
}

/** No page to draw: a symbol the index does not hold, or a filer with no recent
    earnings 8-K, which gives M.A.P. nothing to read. Stated with the reason the
    boundary gave, rather than as a blank page. */
function renderUnknownCompany(ticker, company, filer, manifest) {
  renderMastheadVintage($("masthead-vintage"), manifest);
  renderFooter($("footer"), manifest);

  const main = $("company");
  main.textContent = "";
  const box = document.createElement("div");
  box.className = "cmp-empty";

  const h = document.createElement("h1");
  h.className = "cmp-ticker";
  h.dataset.chrome = "a ticker symbol, not a quantity";
  h.textContent = ticker;

  const what = document.createElement("p");
  what.className = "cmp-standing";
  what.textContent = source.isAbsent(filer)
    ? filer.why
    : source.isAbsent(filer.screen)
      ? filer.screen.why
      : `${ticker} has no earnings 8-K in its recent filings, so there is nothing for M.A.P. to read.`;

  const more = document.createElement("p");
  more.className = "cmp-note";
  more.textContent =
    "Every company that files earnings has a page here: the 120 the frozen corpus holds, with " +
    "their record, and any other filer, with its live runs. Search says which a symbol is.";

  const back = document.createElement("a");
  back.className = "cmp-back";
  back.href = "index.html";
  back.textContent = "← Search";

  box.append(h, what, more, back);
  main.append(box);

  applyPageProvenance();
  enforce();
}

/** A filer's title: ticker, name, and where it stands — the tag that on a corpus
    page names the split names the absence of one. */
function renderFilerTitle(filer) {
  const host = $("page-title");
  if (!host) return;
  host.textContent = "";
  const tick = document.createElement("span");
  tick.className = "page-title-tick";
  tick.dataset.chrome = "a ticker symbol, not a quantity";
  tick.textContent = filer.ticker;
  const name = document.createElement("span");
  if (filer.name) {
    name.textContent = filer.name;
  } else {
    name.className = "page-title-absent";
    name.textContent = "name not in the symbol index";
  }
  const where = document.createElement("span");
  where.className = "tag page-title-split";
  where.dataset.split = "outside";
  where.dataset.chrome = "this company is not in the frozen corpus";
  where.textContent = "outside the corpus";
  host.append(tick, name, where);
}

/** The title IS the company name, with the ticker in mono beside it. The ticker
    is a symbol rather than a quantity, and its digits — BRK-B, FWONK — are part
    of the symbol, so it is marked chrome. */
function renderTitle(company) {
  const host = $("page-title");
  if (!host) return;
  host.textContent = "";

  /* Ticker BEFORE the name, in mono, then the name in serif, then the split.
     The ticker is what was typed to get here and what every other screen keys
     on, so it leads; the name is what the title is. */
  const tick = document.createElement("span");
  tick.className = "page-title-tick";
  tick.dataset.chrome = "a ticker symbol, not a quantity";
  tick.textContent = company.ticker;

  /* A name the export does not carry is a stated absence, not the ticker again.
     `universe.json` holds null when the symbol index was not exported — which is
     what `--allow-partial` produces — and falling back to the ticker printed
     "AAPL AAPL", where the second AAPL looked like the company's name. */
  const name = document.createElement("span");
  if (typeof company.name === "string" && company.name) {
    name.textContent = company.name;
  } else {
    name.className = "page-title-absent";
    name.textContent = "name not exported";
  }

  // The split, as a tag. A factual partition, so no tone: the word carries it.
  const split = document.createElement("span");
  split.className = "tag page-title-split";
  split.dataset.split = company.split;
  split.dataset.chrome = "which half of the panel this company is in";
  split.textContent = company.split;

  host.append(tick, name, split);
}


// A company page is a detail page: neither section is "here".
mountMastheadNav($("masthead-nav"), { current: null });
mountPageRosette($("ground"));
paint();

