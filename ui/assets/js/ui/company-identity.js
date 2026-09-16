/* Section 2 — identity, and the standing paragraph that names the page's nature.

   Every digit on screen is either a figure (provenance-stamped) or positively
   marked chrome. `provenance-audit` has no heuristics, so an unmarked count is a
   violation on the next paint, not a style nit. */

import { chromeText, renderFigure, figure, MEASURED } from "../lib/figure.js";
import { isAbsent } from "../data/source.js";

const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
};

export function renderIdentity(root, { company, runs }) {
  root.textContent = "";
  root.append(el("h2", "cmp-h", "Company"));

  const head = el("div", "cmp-identity");

  const tick = el("span", "cmp-ticker");
  tick.dataset.chrome = "a ticker symbol, not a quantity";
  tick.textContent = company.ticker;
  head.append(tick);

  // No per-split class: the two halves are a factual partition and carry no
  // colour. `data-split` stays as a hook for anything that needs to select on it
  // without implying one half is the notable one.
  const badge = el("span", "cmp-badge", company.split);
  badge.dataset.split = company.split;
  badge.dataset.chrome = "which half of the panel this company is in";
  head.append(badge);

  head.append(el("span", "cmp-name", company.name ?? "name not exported"));
  root.append(head);

  const facts = el("dl", "cmp-facts");
  addFact(facts, "CIK", chromeText(String(company.cik), "an SEC filer id, not a quantity"));
  // Absent, not unknown. The exchange is in symbols.json, and the page does not
  // fetch 864 KB to fill one field.
  addFact(facts, "Exchange", el("em", "cmp-absent", "not loaded"));
  addFact(facts, "Filings held", renderFigure(figure(company.filings.length, MEASURED, "int")));
  /* TWO COUNTS, because they are two things and a page that shows one unlabelled
     disagrees with the search screen for no visible reason. TSLA: 12 panel runs
     and 16 runs in all, the difference being 4 repeats. ACGL: 5 and 5. */
  addFact(facts, "Panel runs", renderFigure(figure(panelRuns(company), MEASURED, "int")));
  addFact(facts, "Runs on this page", renderFigure(figure(countRuns(runs), MEASURED, "int")));
  root.append(facts);

  root.append(standing(company, runs));
  root.append(exchangeNote());
  // NO PRE-SCREEN LINE. `item_202_in_recent` answers "does this company file
  // earnings at all" — a search-screen question, asked before you reach a company.
  // On a page already showing six runs it tells a reader nothing they cannot see.
}

/** Runs the ledger maps to this company's filings — what the search screen
    counts, and what `corpus.json` holds. Excludes repeats and anything outside
    the corpus. */
function panelRuns(company) {
  return company.filings.reduce((n, f) => n + f.run_ids.length, 0);
}

/** Every run for this ticker, across all four document sources: what this page
    actually lists as cards. */
function countRuns(runs) {
  // Four files, counted per source and summed here — never merged into one array
  // and filtered, which is how an out-of-corpus run reaches a corpus figure.
  return Object.values(runs.bySource).reduce((n, rows) => n + rows.length, 0);
}

function standing(company, runs) {
  const rows = Object.values(runs.bySource).flatMap((r) => r);
  const closed = rows.filter((r) => r.outcome_status === "closed").length;

  const p = el("p", "cmp-standing");
  p.append(
    document.createTextNode(
      "This is a record of forecasts already made for this company, not a current " +
        "projection. The export holds no live forecast. Of the ",
    ),
    renderFigure(figure(rows.length, MEASURED, "int")),
    document.createTextNode(" runs on this page, "),
    renderFigure(figure(closed, MEASURED, "int")),
    document.createTextNode(" have closed."),
  );
  return p;
}

function exchangeNote() {
  const p = el("p", "cmp-note");
  p.append(
    chromeText("Exchange sits in symbols.json", "a filename"),
    document.createTextNode(
      ", loaded lazily on the first search keystroke. It is absent here rather " +
        "than unknown: the page does not fetch a megabyte to fill one field.",
    ),
  );
  return p;
}

function addFact(dl, label, valueNode) {
  const pair = document.createElement("div");
  pair.className = "cmp-fact";
  const dt = document.createElement("dt");
  dt.textContent = label;
  const dd = document.createElement("dd");
  dd.append(valueNode);
  pair.append(dt, dd);
  dl.append(pair);
}
