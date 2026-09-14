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

export function renderIdentity(root, { company, runs, series, screen }) {
  root.textContent = "";
  root.append(el("h2", "cmp-h", "Company"));

  const head = el("div", "cmp-identity");

  const tick = el("span", "cmp-ticker");
  tick.dataset.chrome = "a ticker symbol, not a quantity";
  tick.textContent = company.ticker;
  head.append(tick);

  const badge = el("span", `cmp-badge cmp-badge--${company.split}`, company.split);
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
  addFact(facts, "Runs", renderFigure(figure(countRuns(runs), MEASURED, "int")));
  root.append(facts);

  root.append(standing(company, runs));
  root.append(exchangeNote());
  if (!isAbsent(screen)) root.append(filerNote(screen));
}

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
        "projection. The export holds no live forecast. Of its ",
    ),
    renderFigure(figure(rows.length, MEASURED, "int")),
    document.createTextNode(" horizons, "),
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

/** The pre-screen reads only the submissions *recent* block, so it answers
    recency and not history. The copy says so. */
function filerNote(screen) {
  const p = el("p", "cmp-note");
  if (screen.item_202_in_recent) {
    p.append(
      document.createTextNode("This filer published "),
      renderFigure(screen.count),
      document.createTextNode(" "),
      // "Item 2.02 8-K" is a form designation and carries digits in both halves.
      // The audit has no heuristics -- it cannot tell a citation from a quantity
      // -- so the whole designation is marked as chrome rather than left looking
      // like an unmarked figure.
      chromeText("Item 2.02 8-Ks", "an SEC form designation, not a quantity"),
      document.createTextNode(" in its recent EDGAR block."),
    );
  } else {
    p.append(document.createTextNode("No recent earnings 8-K for this filer."));
  }
  return p;
}

function addFact(dl, label, valueNode) {
  const dt = document.createElement("dt");
  dt.textContent = label;
  const dd = document.createElement("dd");
  dd.append(valueNode);
  dl.append(dt, dd);
}
