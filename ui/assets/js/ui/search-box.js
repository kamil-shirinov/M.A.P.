/* The search box and its results.

   The box is the whole point of this screen, so it is first and the rows come
   immediately under it. No prose sits between them: the three groups and the
   "no page" / "nothing to read" cells say what a row is, and anything that
   argues rather than reports lives in the disclosure at the foot of the page.

   Three phases, and the cold one is not dead. `universe.json` is 7.5 KB and
   loads at boot, so the 120 corpus companies resolve before `symbols.json`
   (864 KB) is requested on the first keystroke. Until that file is open this
   module must not say "no matches": absence across 10,398 symbols is not
   knowable from the 120 in memory, and saying it turns a fetch in progress into
   a false negative. */

import { DERIVED, chrome, chromeText, figure, renderFigure } from "../lib/figure.js";

/* Prose that carries digits. The audit has no heuristics and cannot tell a
   citation ("Item 2.02", "8-K") or a count quoted from the export contract from
   a figure this page computed, so every such block is marked with the reason its
   digits are there. A figure the page DOES compute goes through `count()` and is
   provenance-stamped instead. */
const prose = (node, why) => chrome(node, why);
import { isAbsent } from "../data/source.js";
import { stagger } from "../lib/motion.js";

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

const count = (n) => renderFigure(figure(n, DERIVED, "int"));

const PHASE_CHIP = {
  cold: ["index not loaded", "the symbol index has not been requested"],
  fetching: ["fetching · 864 KB", "the size of symbols.json, from the manifest"],
  ready: ["index loaded", "the symbol index is open"],
};

const STATUS = {
  cold:
    "The symbol index is not loaded. It is fetched on your first keystroke, not at boot — " +
    "the 120 corpus companies are already in memory, so a company with a page resolves now.",
  fetching:
    "Loading the symbol index. Corpus hits below are already resolved; everything else waits " +
    "for the file, and until it lands nothing can be called absent.",
  ready:
    "Index loaded. Matched on ticker prefix, then on company name.",
};

/** A name from `listCorpusCompanies` may be an absence, not a string: a null in
    universe.json means the symbol index was not exported, which is not the same
    as a company without a name. */
function nameNode(name) {
  if (isAbsent(name)) return el("span", "srch-absent", "name not exported");
  return el("span", "srch-name", name);
}

/** Exchange is absent for a corpus row by construction — it lives in
    symbols.json, and loading 864 KB to label a row is the eager cost the export
    splits the two files to avoid. Absent, not blank, and not unknown. */
function exchangeNode(exchange) {
  if (exchange === null || exchange === undefined || isAbsent(exchange)) {
    return el("span", "srch-absent", "not loaded");
  }
  return el("span", "srch-ex", exchange);
}

export function mountBox(host, { onQuery }) {
  host.textContent = "";
  /* No section head here any more. "Find a company" is the page title now, in
     serif above this block, and printing it twice made the screen look like it
     had two of them. The note and the index chip stay: they are what this
     section says that the title does not. */
  const head = el("div", "srch-head");
  const note = prose(
    el("span", "srch-note", "every listed symbol is searchable; 120 have a page"),
    "explanatory note; 120 is the corpus size, stated in the export contract",
  );
  const chip = el("span", "srch-chip");
  head.append(note, chip);

  const box = el("div", "srch-box");
  const slash = el("span", "srch-slash", "/");
  const input = document.createElement("input");
  input.type = "search";
  input.className = "srch-input";
  input.placeholder = "ticker or company name";
  input.autocomplete = "off";
  input.spellcheck = false;
  input.setAttribute("aria-label", "Search ticker or company name");
  const right = el("span", "srch-box-right");
  box.append(slash, input, right);

  // Only STATUS.cold carries a digit ("the 120 corpus companies"), but the
  // element is marked once rather than per phase: a later wording change to any
  // of the three must not turn into a violation on a phase nobody re-tested.
  const status = prose(
    el("p", "srch-status"),
    "explanatory status text; 120 is the corpus size",
  );
  host.append(head, box, status);

  input.addEventListener("input", () => onQuery(input.value));

  return {
    input,
    focus: () => input.focus(),
    update({ phase, searchable }) {
      const [label, why] = PHASE_CHIP[phase];
      chip.textContent = "";
      chip.dataset.phase = phase;
      chip.append(chromeText(label, why));

      right.textContent = "";
      right.append(
        phase === "ready"
          ? chromeText("searchable: ", "what the box can match against right now")
          : chromeText("in memory: ", "what the box can match against right now"),
      );
      right.append(searchable === null ? chromeText("index not read", "the index size is not known until the file is open") : count(searchable));

      status.textContent = STATUS[phase];
    },
  };
}

function corpusRow(row) {
  const a = el("a", "srch-row srch-row--corpus");
  // company.html keys on ?ticker=. See notes: it previously accepted only three
  // example names, which gave 117 of the 120 corpus companies no URL.
  a.href = `company.html?ticker=${encodeURIComponent(row.ticker)}`;
  const badge = el("span", "cmp-badge", row.split);
  badge.dataset.split = row.split;
  const counts = el("span", "srch-counts");
  counts.append(
    count(row.filings),
    chromeText(" filings · ", "separator"),
    count(row.runs),
    // NAMED, because the company page counts something else: every run for the
    // ticker, repeats included. TSLA is 12 here and 16 there.
    chromeText(" panel runs", "runs the ledger maps to those filings; repeats are not counted"),
  );
  a.append(
    el("span", "srch-ticker", row.ticker),
    nameNode(row.name),
    exchangeNode(row.exchange),
    badge,
    counts,
    el("span", "srch-go", "→"),
  );
  return a;
}

/** A filer row. The date is the most recent Item 2.02 in the submissions
    *recent block*, which is a slice of filing history and not a calendar window
    — CNTX answers true with a most-recent date in 2023. The row prints the date
    it has and lets the reader judge it. */
function filerRow(row, kind) {
  const div = el("div", `srch-row srch-row--${kind}`);
  const screen = row.screen;
  const detail = el("span", "srch-detail");
  if (isAbsent(screen)) {
    detail.append(chrome(el("span", null, screen.why), "the pre-screen could not answer for this filer"));
  } else if (kind === "earnings") {
    detail.append(
      chromeText("last 2.02 " + screen.most_recent + " · ", "the most recent Item 2.02 in the filer's recent block"),
      renderFigure(screen.count),
      chromeText(" in block", "Item 2.02 filings in the filer's recent block"),
    );
  } else {
    detail.append(
      renderFigure(screen.count),
      chromeText(" in recent block", "Item 2.02 filings in the filer's recent block"),
    );
  }
  div.append(
    el("span", "srch-ticker", row.ticker),
    nameNode(row.name),
    exchangeNode(row.exchange),
    detail,
    el("span", "srch-verdict", kind === "earnings" ? "no page" : "nothing to read"),
  );
  return div;
}

const GROUPS = [
  {
    key: "corpus",
    title: "In the frozen corpus",
    note: "runs, outcomes and a page",
    row: corpusRow,
  },
  {
    key: "earnings",
    title: "Files earnings — not read",
    note: "readable, and outside the freeze — no page",
    row: (r) => filerRow(r, "earnings"),
  },
  {
    key: "none",
    title: "No earnings 8-K in the recent block",
    note: "nothing for M.A.P. to read",
    row: (r) => filerRow(r, "none"),
  },
  {
    /* A FOURTH state the three-outcome spec does not carry, and it is real: a
       symbol can be in symbols.json with no row in filers.json at all —
       `getFilerScreen` answers NOT_APPLICABLE. That is not "no earnings 8-K",
       which is a claim read off a row that exists. */
    key: "unfiled",
    title: "Not in the SEC filer index",
    note: "no filer row to screen — the pre-screen does not apply",
    row: (r) => filerRow(r, "unfiled"),
  },
];

const PER_GROUP = 4;

export function renderResults(host, { phase, query, groups, matched }) {
  host.textContent = "";
  if (!query.trim()) return;

  let shown = 0;
  for (const def of GROUPS) {
    const rows = groups[def.key] ?? [];
    if (!rows.length) continue;
    shown += rows.length;
    const wrap = el("div", "srch-group");
    const head = el("div", "srch-group-head");
    const h3 = el("h3", "cmp-h3", def.title);
    h3.dataset.group = def.key;
    // "No earnings 8-K in the recent block" carries a form designation.
    prose(h3, "a group heading; its digits are an SEC form designation");
    const n = el("span", "srch-group-count");
    n.append(count(rows.length), chromeText(rows.length === 1 ? " match" : " matches", "matches in this group"));
    head.append(h3, n, el("span", "srch-note", def.note));
    wrap.append(head);
    const entering = rows.slice(0, PER_GROUP).map((row) => def.row(row));
    entering.forEach((node) => wrap.append(node));
    stagger(entering);
    if (rows.length > PER_GROUP) {
      const more = el("div", "srch-more");
      more.append(
        chromeText("+", "rows in this group that are not listed"),
        count(rows.length - PER_GROUP),
        chromeText(" more in this group, not listed", "rows in this group that are not listed"),
      );
      wrap.append(more);
    }
    host.append(wrap);
  }

  /* The one sentence the results screen earns, because it states a cut the rows
     cannot: what was left out, and that the order is not a ranking. */
  if (shown) {
    const note = el("p", "srch-cut");
    note.append(
      chromeText("Showing at most " + PER_GROUP + " rows per group of ", "the per-group cut"),
      count(matched),
      chromeText(" matched. ", "total matches for this term"),
      document.createTextNode(
        "The export is not ranked: an exact ticker comes first, then alphabetical order, " +
          "because nothing in these files states which symbol you meant.",
      ),
    );
    host.append(note);
    return;
  }

  /* Nothing matched. What that MEANS depends on whether the index is open. */
  const box = el("p", "srch-empty");
  if (phase === "ready") {
    box.append(
      document.createTextNode("No symbol in the index matches "),
      el("code", null, query.trim()),
      document.createTextNode("."),
    );
  } else {
    box.dataset.pending = "true";
    // Reached only in the window between a keystroke and symbols.json landing,
    // with no corpus hit -- so it is transient, and an audit sampling before or
    // after it sees nothing. Marked because "the 120 companies" is a count.
    prose(box, "explanatory prose; 120 is the corpus size held in memory");
    box.append(
      document.createTextNode("No corpus company matches "),
      el("code", null, query.trim()),
      document.createTextNode(
        " yet, and that is all this page can say right now. The 120 companies are in memory; " +
          "the rest of the index is still on the wire, and absence across it is not knowable until it lands.",
      ),
    );
  }
  host.append(box);
}
