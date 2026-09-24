/* Composition root for the company page.

   A RECORD OF FORECASTS ALREADY MADE, for one company. The export holds no live
   forecast and cannot: the newest anchor is 2026-08-13 and 777 of 779 horizons
   have closed. Nothing here projects.

   The `example` prop picks which company to show. Three exist because the
   distinctive states live on one or two companies each and must not drive the
   layout:

     typical  ACHC — six ledger runs, both bands, all closed, no drift. 40
              companies present exactly this shape; 67 present the profile at
              some run count. This is what a reviewer opens.
     ati      ATI  — a repeat whose panel run does not exist.
     aapl     AAPL — outside-corpus runs, an open window, and drift.

   Read `?example=ati` from the query string so a reviewer can reach a state
   without it pretending to be common. */

import * as source from "./data/source.js";
import { renderIdentity } from "./ui/company-identity.js";
import { renderSeries } from "./ui/company-series.js";
import { renderFilings } from "./ui/company-filings.js";
import { renderRuns } from "./ui/company-runs.js";
import { renderScoring } from "./ui/company-scoring.js";
import { renderFooter, renderMastheadVintage } from "./ui/company-footer.js";
import { applyPageProvenance, enforce } from "./lib/provenance-audit.js";
import { mountMastheadNav } from "./ui/front-door.js";

const EXAMPLES = { typical: "ACHC", ati: "ATI", aapl: "AAPL" };

const $ = (id) => document.getElementById(id);

/** Disclosure state, keyed on RUN ID and never on row index.

    An anchor can repeat within a company — ATI has two runs whose anchors sit a
    day apart, and a paginated or filtered ledger reorders freely — so an
    index-keyed open row follows the position rather than the run. */
const open = new Set();

/** Two ways in, and they are not the same thing.

    ?ticker=  a link from search. Any of the 120 corpus companies — and any
              string at all, since a URL can be typed.
    ?example= the review form: one of three names, each chosen because it carries
              a state the layout must not be driven by.

    `body[data-example]` reads "linked" for a ticker link rather than an example
    name, so styling keyed on an example cannot silently apply to an arbitrary
    company. */
function target() {
  const params = new URLSearchParams(location.search);
  const linked = params.get("ticker");
  if (linked && linked.trim()) {
    return { mode: "linked", ticker: linked.trim().toUpperCase() };
  }
  const asked = params.get("example") ?? "typical";
  const mode = EXAMPLES[asked] ? asked : "typical";
  return { mode, ticker: EXAMPLES[mode] };
}

async function paint() {
  const { mode, ticker } = target();
  document.body.dataset.example = mode;

  const [state, company, runs, series, scoring] = await Promise.all([
    source.getExportState(),
    source.getCompany(ticker),
    source.listRuns(ticker),
    source.getPriceSeries(ticker),
    source.listScoringRecords(),
  ]);

  if (state.state === source.NO_EXPORT) {
    renderNoExport(state);
    return;
  }

  /* A hand-typed or stale ?ticker= reaches a company the corpus does not hold.
     `getCompany` answers NOT_APPLICABLE for it, and every section below assumes
     a company object — `renderIdentity` would print `undefined` and
     `renderFilings` would throw on `company.filings`. So the absence is rendered
     here, as a stated fact with the reason the boundary gave, rather than as a
     blank page or a stack trace. */
  if (source.isAbsent(company)) {
    renderUnknownCompany(ticker, company, state.manifest);
    return;
  }

  renderMastheadVintage($("masthead-vintage"), state.manifest);
  renderIdentity($("identity"), { company, runs });
  renderSeries($("series"), { series, runs });
  renderFilings($("filings"), { company, runs });
  renderRuns($("runs"), {
    runs,
    company,
    open,
    onToggle: (runId) => {
      // Keyed on run_id. See `open` above.
      if (open.has(runId)) open.delete(runId);
      else open.add(runId);
      paint();
    },
  });
  renderScoring($("scoring"), { scoring, company });
  renderFooter($("footer"), state.manifest);

  applyPageProvenance();
  enforce();
}

/** The one state the export cannot describe for itself: there is no manifest to
    read an absence from, so this module states it. Distinct from a partial
    export, which exists and names its own gaps. */
function renderNoExport(state) {
  const main = $("company");
  main.textContent = "";
  const box = document.createElement("div");
  box.className = "cmp-empty";
  box.dataset.chrome = "no export is present; nothing on screen is a figure";
  const h = document.createElement("h1");
  h.textContent = "No export";
  const p = document.createElement("p");
  p.textContent = state.why.why;
  const pre = document.createElement("pre");
  pre.textContent = state.why.remedy;
  box.append(h, p, pre);
  main.append(box);
  $("footer").textContent = "";
  $("masthead-vintage").textContent = "";
}

/** Not in the frozen corpus. The export can say that much and no more: there is
    no page for a company it never read, and the 120 that have one are listed on
    the search screen. */
function renderUnknownCompany(ticker, absence, manifest) {
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
  what.textContent = absence.why;

  const more = document.createElement("p");
  more.className = "cmp-note";
  more.textContent =
    "This page exists for the companies the frozen corpus holds, because it is a " +
    "record of forecasts already made and there are none to show for any other. " +
    "Search lists every symbol and says which of them have one.";

  const back = document.createElement("a");
  back.className = "cmp-back";
  back.href = "index.html";
  back.textContent = "← Search";

  box.append(h, what, more, back);
  main.append(box);

  applyPageProvenance();
  enforce();
}

// A company page is a detail page: neither section is "here".
mountMastheadNav($("masthead-nav"), { current: null });
paint();
