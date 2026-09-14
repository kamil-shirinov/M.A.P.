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

const EXAMPLES = { typical: "ACHC", ati: "ATI", aapl: "AAPL" };

const $ = (id) => document.getElementById(id);

/** Disclosure state, keyed on RUN ID and never on row index.

    An anchor can repeat within a company — ATI has two runs whose anchors sit a
    day apart, and a paginated or filtered ledger reorders freely — so an
    index-keyed open row follows the position rather than the run. */
const open = new Set();

function example() {
  const asked = new URLSearchParams(location.search).get("example") ?? "typical";
  return EXAMPLES[asked] ? asked : "typical";
}

async function paint() {
  const which = example();
  const ticker = EXAMPLES[which];
  document.body.dataset.example = which;

  const [state, company, runs, series, scoring, screen] = await Promise.all([
    source.getExportState(),
    source.getCompany(ticker),
    source.listRuns(ticker),
    source.getPriceSeries(ticker),
    source.listScoringRecords(),
    source.getFilerScreen(ticker),
  ]);

  if (state.state === source.NO_EXPORT) {
    renderNoExport(state);
    return;
  }

  renderMastheadVintage($("masthead-vintage"), state.manifest);
  renderIdentity($("identity"), { company, runs, series, screen });
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

paint();
