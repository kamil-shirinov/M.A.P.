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

export function renderIdentity(root, { company, runs, liveRuns = 0 }) {
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
  addFact(facts, "Runs in the record", renderFigure(figure(countRuns(runs), MEASURED, "int")));

  /* TWO NEW FACTS, both about what is NOT here.

     `Closed` answers the question the table raises and does not summarise: of
     the runs on this page, how many have an outcome at all. Derived, because the
     page counts it.

     `Live runs` counts the section at the foot of the page, and only that. It
     used to read "Live forecast: none in export", which stopped being true when
     live runs moved onto this page (ADR 0036, amendment of 2026-09-30). */
  const closed = countRuns(runs) - openRuns(runs);
  addFact(facts, "Closed", closedFact(closed, countRuns(runs)));
  addFact(facts, "Live runs", liveFact(liveRuns));
  root.append(facts);
  // NO PRE-SCREEN LINE. `item_202_in_recent` answers "does this company file
  // earnings at all" — a search-screen question, asked before you reach a company.
  // On a page already showing six runs it tells a reader nothing they cannot see.
}

/** Live runs, counted on their own and never added to a record count.

    A link to the section that lists them, because the number is only worth
    reading next to what it counts, and that is at the foot of the page. */
export function liveFact(count) {
  const a = el("a", "cmp-live-link");
  a.href = "#live";
  a.append(
    renderFigure(figure(count, MEASURED, "int")),
    chromeText(" below, outside the record", "where live runs are listed and why they are apart"),
  );
  return a;
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

/** Every run in the record for this ticker: the corpus and the runs that predate
    the source field. Live runs are passed in separately and never reach here. */
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

/** The strip for a company outside the corpus: what the export knows without
    having read it. No filings held, no panel runs, no closed count — those are
    properties of a record, and this page has none. Stating them as zeros would
    read as a record that is empty rather than one that does not exist. */
export function renderFilerIdentity(root, { filer, liveRuns = 0, earlierRuns = 0 }) {
  root.textContent = "";
  const facts = el("dl", "cmp-facts");
  addFact(facts, "CIK", chromeText(String(filer.cik), "an SEC filer id, not a quantity"));
  addFact(
    facts,
    "Exchange",
    filer.exchange ? el("span", null, filer.exchange) : el("em", "cmp-absent", "not in the symbol index"),
  );
  const screen = filer.screen;
  if (isAbsent(screen)) {
    addFact(facts, "Earnings filings", el("em", "cmp-absent", screen.why));
  } else {
    /* From the pre-screen, which reads only the submissions RECENT block — a
       slice of filing history, not a calendar window — so the label says so. */
    addFact(facts, "Earnings filings, recent block", renderFigure(screen.count));
    addFact(facts, "Latest", chromeText(screen.most_recent ?? "none", "the date of the latest Item 2.02 in the recent block"));
    addFact(facts, "Screened", chromeText(screen.fetched_on, "the day the pre-screen read EDGAR"));
  }
  addFact(facts, "Live runs", liveFact(liveRuns));
  if (earlierRuns > 0) {
    /* Runs from before the document-source field. They make no claim either way,
       so they are not live runs and there is no record to put them in; the runs
       screen lists them with that label. */
    const a = el("a", "cmp-live-link");
    a.href = `runs.html?ticker=${encodeURIComponent(filer.ticker)}`;
    a.append(
      renderFigure(figure(earlierRuns, MEASURED, "int")),
      chromeText(" on the runs screen", "runs whose manifest predates the source field"),
    );
    addFact(facts, "Earlier runs", a);
  }
  root.append(facts);
}
