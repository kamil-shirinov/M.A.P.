/* Section 2 — identity, and the standing paragraph that names the page's nature.

   Every digit on screen is either a figure (provenance-stamped) or positively
   marked chrome. `provenance-audit` has no heuristics, so an unmarked count is a
   violation on the next paint, not a style nit. */

import { chromeText, renderFigure, figure, DERIVED, MEASURED } from "../lib/figure.js";
import { SOURCES, isAbsent } from "../data/source.js";

const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
};

export function renderIdentity(root, { company, runs }) {
  root.textContent = "";
  /* No "Company" head and no repeated ticker: the page title above IS the
     company name with its ticker beside it, and printing both made the top of
     the page read as two headers stacked. What stays here is what the title
     cannot carry — the split badge, the CIK, the exchange and the counts. */
  /* The split badge moved into the page title, beside the name, where it reads
     as a property of the company rather than as the first row of a table. */
  const facts = el("dl", "cmp-facts");
  addFact(facts, "CIK", chromeText(String(company.cik), "an SEC filer id, not a quantity"));
  // Absent, not unknown. The exchange is in symbols.json, and the page does not
  // fetch 864 KB to fill one field.
  /* From corpus.json, which this page already has open. It said "not loaded"
     because the field used to live only in symbols.json; the export carries it
     on the corpus row now. */
  addFact(
    facts,
    "Exchange",
    company.exchange
      ? el("span", null, company.exchange)
      : el("em", "cmp-absent", "not in this export"),
  );
  addFact(facts, "Filings held", renderFigure(figure(company.filings.length, MEASURED, "int")));
  /* TWO COUNTS, because they are two things and a page that shows one unlabelled
     disagrees with the search screen for no visible reason. TSLA: 12 panel runs
     and 16 runs in all, the difference being 4 repeats. ACGL: 5 and 5. */
  addFact(facts, "Panel runs", renderFigure(figure(panelRuns(company), MEASURED, "int")));
  addFact(facts, "Runs on this page", renderFigure(figure(countRuns(runs), MEASURED, "int")));

  /* TWO NEW FACTS, both about what is NOT here.

     `Closed` answers the question the table raises and does not summarise: of
     the runs on this page, how many have an outcome at all. Derived, because the
     page counts it.

     `Live forecast` is a stated absence. This export is a log of runs that have
     already happened; nothing in it is a current view, and a page that says
     nothing invites the reader to assume the newest row is one. */
  const closed = countRuns(runs) - openRuns(runs);
  addFact(facts, "Closed", closedFact(closed, countRuns(runs)));
  addFact(facts, "Live forecast", el("em", "cmp-absent", "none in export"));
  root.append(facts);
  // NO PRE-SCREEN LINE. `item_202_in_recent` answers "does this company file
  // earnings at all" — a search-screen question, asked before you reach a company.
  // On a page already showing six runs it tells a reader nothing they cannot see.
}

/** "9 of 11", both derived here: the page counted the rows it is showing. */
function closedFact(closed, total) {
  const span = el("span");
  span.append(
    renderFigure(figure(closed, DERIVED, "int")),
    chromeText(" of ", "a ratio of counts"),
    renderFigure(figure(total, DERIVED, "int")),
  );
  return span;
}

const openRuns = (runs) =>
  SOURCES.reduce((n, name) => n + runs.bySource[name].filter((r) => isAbsent(r.outcome)).length, 0);

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
