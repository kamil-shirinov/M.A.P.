/* The top of the runs screen: what this page counts, the four files it counts
   it from, and the two populations that sit beside the journal rather than in
   it — filings that never ran, and runs whose price series moved under them.

   THE TOTAL IS POOLED HERE, IN SIGHT. The export writes one count per document
   source and no total, because the four populations are not one list. A screen
   headed "779 runs" is adding them, so the addition happens on this page, is
   marked derived, and prints its own arithmetic under the population cells.

   `ledger.items_settled` (709) never appears on this screen. It counts corpus
   items — 701 completed plus 8 terminal failures — and this page counts runs. */

import { DERIVED, MEASURED, chromeText, derive, figure, renderFigure } from "../lib/figure.js";
import { SOURCES } from "../data/source.js";
import { fmt } from "../lib/format.js";

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

const card = (root, title, note) => {
  root.textContent = "";
  const box = el("div", "runs-card");
  const head = document.createElement("header");
  head.append(el("h2", null, title));
  if (note) head.append(el("span", "runs-note", note));
  box.append(head);
  root.append(box);
  return { box, head };
};

/* The per-cell sentences moved to the page-foot disclosure. A cell is a path, a
   count, a size and whether it was read; what each source MEANS is a note, and
   four of them stacked beside four numbers made the strip read as prose. */
const WHAT = { corpus: "", edgar: "", news: "", unknown: "" };

/** Section 2. The count, what it is counted across, and the one scope line. */
export function renderIdentity(root, { rows, counts, universe }) {
  root.textContent = "";
  const box = el("div", "runs-card");
  const grid = el("div", "runs-identity");

  const perSource = SOURCES.map((s) => figure(counts[s], MEASURED, "int"));
  const total = derive(perSource.reduce((n, f) => n + f.value, 0), "int", ...perSource);
  const totalNode = renderFigure(total);
  totalNode.title = "Summed on this page across the four document-source files";

  const left = document.createElement("div");
  /* One mono fact line, not a headline number plus a sentence. The page title
     above says what this screen is; this says how much of it there is. */
  const line = el("div", "runs-total");
  line.append(totalNode, el("span", "runs-total-word", "runs"));
  left.append(line);

  /* Read off the rows, not off the manifest: these are properties of what was
     read. Before the journal lands they are absent rather than zero. */
  const sub = el("p", "runs-subline");
  if (rows.length) {
    const dates = rows.map((r) => r.anchor_date);
    sub.append(
      chromeText("across ", "what the count is counted across"),
      renderFigure(derive(new Set(rows.map((r) => r.ticker)).size, "int")),
      chromeText(" tickers and ", "what the count is counted across"),
      renderFigure(derive(new Set(dates).size, "int")),
      chromeText(" anchor dates, ", "what the count is counted across"),
      chromeText(fmt.date(dates.reduce((a, b) => (a < b ? a : b))), "the oldest anchor in the journal"),
      chromeText(" to ", "a date range"),
      chromeText(fmt.date(dates.reduce((a, b) => (a > b ? a : b))), "the newest anchor in the journal"),
    );
  } else {
    sub.append(chromeText("across the four document-source files, not yet read", "the journal has not landed"));
  }
  left.append(sub);

  /* The middle column. Two columns pinned a definition list to the right edge of
     a 1600px card and left the middle empty; this sentence belongs somewhere a
     reader looks first, and it fills the hole rather than sitting under it. */
  /* A STATED ABSENCE, in the form the rest of the app uses for one: the label
     "not here", then what is not here. As a paragraph it read as context; as an
     absence it reads as a boundary, which is what it is. */
  const scope = el("div", "runs-scope");
  scope.append(
    el("span", "runs-absent-k", "not here"),
    chromeText(
      "786 runs of the four-arm ablation, outside the export",
      "786 is quoted from the project's own record of the ablation, not counted from these files",
    ),
  );

  const defs = el("dl", "runs-defs");
  const def = (k, node) => { defs.append(el("dt", null, k)); const dd = el("dd"); dd.append(node); defs.append(dd); };
  def("Rows", chromeText("runs, newest anchor first", "how the rows are ordered"));
  const hz = document.createElement("span");
  if (rows.length) {
    const byH = tally(rows.map((r) => r.horizon_days));
    const parts = [...byH.entries()].sort((a, b) => a[0] - b[0]);
    parts.forEach(([h, n], i) => {
      if (i) hz.append(chromeText(" · ", "a separator"));
      hz.append(chromeText(`${h} sessions × `, "the forecast horizon in sessions"), renderFigure(derive(n, "int")));
    });
  } else hz.append(chromeText("not read yet", "the journal has not landed"));
  def("Horizon", hz);
  const sp = document.createElement("span");
  if (rows.length) {
    // Split is the TICKER's, from universe.json — a run does not carry one.
    const bySplit = tally(rows.map((r) => universe.get(r.ticker)?.split ?? "unrecorded"));
    [...bySplit.entries()].sort().forEach(([k, n], i) => {
      if (i) sp.append(chromeText(" · ", "a separator"));
      sp.append(renderFigure(derive(n, "int")), chromeText(` ${k}`, "the corpus split the ticker belongs to"));
    });
  } else sp.append(chromeText("not read yet", "the journal has not landed"));
  def("Split", sp);

  grid.append(left, scope, defs);
  box.append(grid);
  root.append(box);
}

/** Section 3. One cell per file, and the arithmetic that adds them. */
export function renderPopulations(root, { manifest, journal, counts }) {
  const { box, head } = card(root, "Four populations, kept apart");

  const check = el("span", "runs-note runs-note--right runs-check");
  if (!journal) {
    check.dataset.agree = "true";
    check.append(chromeText("rows not read yet", "the journal file has not landed"));
  } else {
    const agree = SOURCES.every((s) => journal.bySource[s].length === counts[s]);
    check.dataset.agree = String(agree);
    check.append(chromeText(
      agree ? "rows read agree with the manifest" : "rows read disagree with the manifest",
      "a live comparison of rows read against the manifest's own count",
    ));
  }
  head.append(check);

  const grid = el("div", "runs-pops");
  for (const name of SOURCES) {
    const cell = el("div", "runs-pop");
    const n = counts[name];
    cell.dataset.empty = String(n === 0);
    cell.append(el("span", "runs-pop-file", `runs/by_source/${name}.json`));
    cell.append(renderFigure(figure(n, MEASURED, "int")));
    const size = manifest?.files?.[`runs/by_source/${name}.json`];
    const state = el("span", "runs-pop-state");
    state.append(chromeText(size === undefined ? "size not stated" : fmt.kb(size), "the file's size, from the manifest"));
    state.append(chromeText(
      !journal ? " · reading" : n === 0 ? " · read · []" : " · read · shown below",
      "whether this file has been read yet",
    ));
    cell.append(state);
    if (WHAT[name]) cell.append(el("p", "runs-pop-what", WHAT[name]));
    grid.append(cell);
  }
  box.append(grid);

  /* The arithmetic, shown. The export writes one count per file and no total,
     so the sum is the page's and it is DERIVED — the dotted mark says so. The
     paragraph that used to sit beside it is in the disclosure. */
  const foot = el("div", "runs-pops-foot");
  const sum = el("p", "runs-sum");
  const per = SOURCES.map((s) => figure(counts[s], MEASURED, "int"));
  per.forEach((f, i) => {
    if (i) sum.append(chromeText(" + ", "an arithmetic operator"));
    sum.append(renderFigure(f));
  });
  sum.append(chromeText(" = ", "an arithmetic operator"));
  sum.append(renderFigure(derive(per.reduce((n, f) => n + f.value, 0), "int", ...per)));
  sum.append(el("span", "runs-sum-why", "summed here · the export writes no total"));
  foot.append(sum);
  box.append(foot);
}

/** Section 4a. Filings the corpus settled that no run ever read. */
export function renderUnrun(root, { filings }) {
  const { box, head } = card(root, "Filings with no run");
  const count = el("span", "runs-note runs-note--right");
  count.append(renderFigure(derive(filings.length, "int")), chromeText(" of the corpus's filings", "filings the corpus holds that no run read"));
  head.append(count);

  const cells = el("div", "runs-cells");
  for (const f of filings) {
    const a = el("a", "runs-cell");
    a.href = `company.html?ticker=${encodeURIComponent(f.ticker)}`;
    a.append(el("span", "t", f.ticker));
    a.append(chromeText(fmt.date(f.filed), "the date the filing was filed"));
    a.append(el("span", "m", `${f.band} · ${f.split}`));
    cells.append(a);
  }
  box.append(cells);
}

/** Section 4b. Runs whose price basis moved after the forecast was written. */
export function renderDrift(root, { rows, total, selected, onSelect }) {
  const { box, head } = card(root, "Re-based since the run");
  box.classList.add("runs-drift");
  const drifted = rows.filter((r) => !r.anchor_drift.absent);
  const count = el("span", "runs-note runs-note--right");
  count.append(renderFigure(derive(drifted.length, "int")), chromeText(" of ", "of the journal"), renderFigure(derive(total, "int")), chromeText(" runs", "runs in the journal"));
  head.append(count);

  /* Grouped on TICKER. The ratio is computed per run from that run's own float32
     spot, so nine rows carry seven distinct values for two corporate actions;
     grouping on it would make one group per run. */
  const byTicker = new Map();
  for (const r of drifted) {
    if (!byTicker.has(r.ticker)) byTicker.set(r.ticker, []);
    byTicker.get(r.ticker).push(r);
  }
  const acts = el("div", "runs-acts");
  for (const [ticker, list] of byTicker) {
    const b = el("button", "runs-act");
    b.type = "button";
    b.setAttribute("aria-pressed", String(selected === ticker));
    b.append(el("span", "t", ticker));
    b.append(renderFigure(derive(list.length, "int")), chromeText(" runs · ", "runs of this ticker that were re-based"));
    b.append(chromeText("×", "the ratio the snapshot moved by"), renderFigure(list[0].anchor_drift.ratio));
    /* The size of the action, DERIVED as 1 ÷ ratio rather than named. The export
       carries a ratio and nothing else: calling it "a 1.012 split" quotes a
       profile, and a split is one of several actions that produce this shape. */
    const act = derive(1 / list[0].anchor_drift.ratio.value, "ratio", list[0].anchor_drift.ratio);
    const why = el("span", "why");
    why.append(chromeText(" · corporate action ×", "the size of the action, computed here as 1 ÷ the ratio"), renderFigure(act));
    b.append(why);
    b.addEventListener("click", () => onSelect(selected === ticker ? null : ticker));
    acts.append(b);
  }
  box.append(acts);
  // "Selecting one sets the ticker filter" is gone: the buttons are buttons and
  // the hover says so. Why the grouping is on ticker is in the disclosure.
}

function tally(values) {
  const m = new Map();
  for (const v of values) m.set(v, (m.get(v) ?? 0) + 1);
  return m;
}
