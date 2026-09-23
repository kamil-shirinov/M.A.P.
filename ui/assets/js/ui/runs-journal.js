/* The journal: every run in the export, grouped by quarter of its anchor.

   WHY QUARTERS. Months run from 3 runs to 97 — a stub and a wall in the same
   control. Quarters hold 83 to 191, which is a list a reader can open on
   purpose. The month chart above keeps the seasonal shape that grouping loses.

   THERE IS NO SCORE COLUMN, and there cannot be one. Scoring records key their
   items on ticker and `as_of`; a run carries `run_id` and `anchor_date`. Nothing
   joins them, and a column that guessed would be right often enough to look
   right. Each row pairs a run's scenarios with its own outcome: both come off
   the same row, which is the only pairing this screen can make.

   REALISED IS A LOG RETURN SHOWN AS THE SIMPLE RETURN IT EQUALS. The export
   stores log; `fmt.logpct` applies expm1 before printing, so the number on
   screen is the simple return. The legend says so, and so does every row
   detail, because a column headed "Realised" states no convention at all. */

import { chromeText, derive, renderFigure } from "../lib/figure.js";
import { describeCorpusRelation, describeDrift, describeOutcome, isAbsent } from "../data/source.js";
import { fmt } from "../lib/format.js";
import { RELATIONS } from "./runs-filters.js";

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

const REL_DETAIL = {
  repeat_of_exhibit: "second pass on an exhibit",
  outside_corpus: "document not in corpus",
  unchecked: "no ledger in export",
};

const COLUMNS = [
  ["Anchored", "the trading session each run opened from"],
  ["Company", null],
  ["Run", "the first eight characters of each run's id"],
  ["Relation", null],
  ["Split", null],
  ["Freeze", "the frozen corpus version each run executed under"],
  ["Hzn", "the horizon in sessions"],
  ["Anchor close", null],
  ["Outcome close", null],
  ["Realised", null],
];

/** Parts (text / chrome / figure) onto a node. Never string interpolation: a
    date welded into a template is a number the audit cannot see. */
function appendParts(node, parts) {
  for (const part of parts) {
    if (part.kind === "figure") node.append(renderFigure(part.figure));
    else if (part.kind === "chrome") node.append(chromeText(part.text, part.why));
    else node.append(document.createTextNode(part.text));
  }
}

export function renderJournal(root, ctx) {
  root.textContent = "";
  const box = el("div", "runs-card");
  const head = document.createElement("header");
  head.append(el("h2", null, "Journal"));
  head.append(el("span", "runs-note", "every file in source order; only unknown has rows · newest first, as written"));
  const showing = el("span", "runs-note runs-note--right");
  if (ctx.rows.length) {
    showing.append(chromeText("showing ", "how many rows the filters show"),
      renderFigure(derive(ctx.filtered.length, "int")),
      chromeText(" of ", "of the journal"),
      renderFigure(derive(ctx.rows.length, "int")));
  }
  head.append(showing);
  box.append(head);

  box.append(el("p", "runs-inset",
    "There is no score column, and there cannot be one. Scoring records key their items on " +
    "ticker and as_of, never run_id, so nothing joins a score to a row. Each row pairs a run's " +
    "scenarios with its own outcome and nothing else. Scoring is shown whole on company pages, " +
    "related at band, split and vintage."));

  const filters = el("div");
  const chart = el("div");
  box.append(filters, chart);
  root.append(box);

  if (ctx.state !== "ready") {
    box.append(stateBox(ctx));
    return { filters, chart };
  }
  if (!ctx.filtered.length) {
    const p = el("p", "runs-state");
    p.append(chromeText(
      `No run matches ${ctx.describe.join(" · ")} together.`,
      "the filters currently applied"),
      document.createTextNode(" Each filter has runs on its own; this combination has none."));
    box.append(p);
    return { filters, chart };
  }

  const rule = el("p", "runs-rule");
  if (ctx.allOpen) {
    rule.append(document.createTextNode("All "), renderFigure(derive(ctx.filtered.length, "int")),
      chromeText(" matching runs are open — at 60 or fewer, groups stop earning their collapse.",
        "60 is this page's threshold for collapsing groups at all"));
  } else {
    rule.append(
      document.createTextNode("Grouped by quarter of anchor date; quarters here hold "),
      renderFigure(derive(ctx.span.min, "int")), document.createTextNode(" to "),
      renderFigure(derive(ctx.span.max, "int")), document.createTextNode(" runs where months hold "),
      renderFigure(derive(ctx.monthSpan.min, "int")), document.createTextNode(" to "),
      renderFigure(derive(ctx.monthSpan.max, "int")),
      document.createTextNode(". The newest group opens; the rest wait. A dated row repeats its date in grey."));
  }
  box.append(rule);

  for (const group of ctx.groups) box.append(groupBlock(group, ctx));
  box.append(legend());
  return { filters, chart };
}

function stateBox(ctx) {
  const p = el("p", "runs-state");
  if (ctx.state === "reading") {
    p.append(chromeText(
      `Reading runs/by_source/unknown.json — ${fmt.kb(ctx.readingSize ?? 649217)}.`,
      "the size of the file being read, from the manifest"),
      document.createTextNode(" The front door counts runs from the manifest; this is the one screen that opens the file."));
    return p;
  }
  if (ctx.state === "no-export") {
    p.append(document.createTextNode(ctx.error.why));
    if (ctx.error.remedy) p.append(Object.assign(document.createElement("pre"), { textContent: ctx.error.remedy }));
    return p;
  }
  p.append(document.createTextNode(`Could not read the export: ${ctx.error}`));
  return p;
}

function groupBlock(group, ctx) {
  const wrap = el("div", "runs-group");
  wrap.dataset.drift = String(group.drift > 0);
  const isOpen = ctx.openGroups.has(group.label);

  const head = el("button", "runs-group-head");
  head.type = "button";
  head.setAttribute("aria-expanded", String(isOpen));
  head.append(el("span", null, isOpen ? "▾" : "▸"));
  head.append(chromeText(group.label, "the calendar quarter of the anchor date"));
  const n = el("span", "runs-group-n");
  if (group.rows.length === group.total) {
    n.append(renderFigure(derive(group.rows.length, "int")), chromeText(group.rows.length === 1 ? " run" : " runs", "runs in this group"));
  } else {
    n.append(renderFigure(derive(group.rows.length, "int")), chromeText(" of ", "of the group"), renderFigure(derive(group.total, "int")), chromeText(" runs", "runs in this group"));
  }
  head.append(n);
  const months = el("span", "runs-group-months");
  group.months.forEach(([label, count], i) => {
    if (i) months.append(chromeText(" · ", "a separator"));
    months.append(chromeText(`${label} `, "a month inside this quarter"), renderFigure(derive(count, "int")));
  });
  head.append(months);

  const marks = el("span", "runs-group-marks");
  if (group.open) {
    const m = el("span", "runs-mark runs-mark--open");
    m.append(renderFigure(derive(group.open, "int")), chromeText(" window open", "runs whose horizon has not elapsed"));
    marks.append(m);
  }
  if (group.drift) {
    const m = el("span", "runs-mark runs-mark--drift");
    m.append(renderFigure(derive(group.drift, "int")), chromeText(" re-based", "runs whose price series was re-based since the run"));
    marks.append(m);
  }
  const d = el("span", "runs-mark runs-mark--dates");
  d.append(renderFigure(derive(group.dates, "int")), chromeText(group.dates === 1 ? " anchor date" : " anchor dates", "distinct anchor dates in this group"));
  marks.append(d);
  head.append(marks);
  head.addEventListener("click", () => ctx.onToggleGroup(group.label));
  wrap.append(head);
  wrap.id = `q-${group.label.replace(/\s+/g, "-")}`;

  if (!isOpen) return wrap;

  const header = el("div", "runs-colhead");
  for (const [label, why] of COLUMNS) {
    header.append(why ? chromeText(label, why) : el("span", null, label));
  }
  wrap.append(header);

  // Only expanded groups render rows: the largest is 191.
  let previousDate = null;
  for (const run of group.rows) {
    wrap.append(rowLine(run, ctx, run.anchor_date === previousDate));
    if (ctx.openRows.has(run.run_id)) wrap.append(detail(run, ctx));
    previousDate = run.anchor_date;
  }
  return wrap;
}

function rowLine(run, ctx, ditto) {
  const row = el("button", "runs-row");
  row.type = "button";
  const drifted = !isAbsent(run.anchor_drift);
  row.dataset.drift = String(drifted);
  row.dataset.open = String(ctx.openRows.has(run.run_id));
  row.setAttribute("aria-expanded", String(ctx.openRows.has(run.run_id)));

  // The date is never omitted — a blank cell reads as missing data. A repeat
  // within the group prints in the rule colour instead.
  const date = chromeText(run.anchor_date, "the trading session this run opened from");
  date.className = "runs-c-date";
  date.dataset.ditto = String(ditto);
  row.append(date);

  const co = el("span", "runs-c-co");
  co.append(el("span", "t", run.ticker));
  const name = ctx.universe.get(run.ticker)?.name;
  // Phillips 66. A company name is chrome: it carries digits that are part of a
  // name and not a quantity, and the audit has no way to tell those apart.
  const nameNode = !name || isAbsent(name)
    ? el("span", null, "name not exported")
    : chromeText(name, "a company name, which can contain digits");
  nameNode.classList.add("n");
  co.append(nameNode);
  row.append(co);

  // Eight characters, matching the company page. Five are already unique across
  // all 779; the extra three cost nothing and keep one abbreviation everywhere.
  const id = chromeText(run.run_id.slice(0, 8), "the first eight characters of this run's id");
  id.className = "runs-c-id";
  row.append(id);

  const rel = el("span", "runs-c-rel");
  const tag = el("span", "runs-tag", RELATIONS.find(([v]) => v === run.corpus_relation)?.[1] ?? run.corpus_relation);
  tag.dataset.rel = run.corpus_relation;
  rel.append(tag);
  if (run.corpus_relation === "ledger_item" && !isAbsent(run.ledger_item)) {
    const d = el("span", "d");
    // Carried from the ledger. Never derived from the anchor: the anchor equals
    // the filing date on 66 of 701 runs and filing + 1 on the other 635.
    d.append(chromeText("filed ", "the filing this run read, carried from the ledger"),
      chromeText(run.ledger_item.filing_date, "the filing date, read from the ledger"),
      chromeText(` · ${run.ledger_item.band}`, "the band the ledger filed it under"));
    rel.append(d);
  } else if (REL_DETAIL[run.corpus_relation]) {
    rel.append(el("span", "d", REL_DETAIL[run.corpus_relation]));
  }
  row.append(rel);

  row.append(el("span", "runs-c-split", ctx.universe.get(run.ticker)?.split ?? "—"));

  const freeze = isAbsent(run.freeze_version)
    ? el("span", "runs-c-freeze", "unrecorded")
    : chromeText(run.freeze_version, "the frozen corpus this run executed under");
  freeze.className = "runs-c-freeze";
  freeze.dataset.absent = String(isAbsent(run.freeze_version));
  row.append(freeze);

  const hzn = chromeText(String(run.horizon_days), "the horizon in sessions");
  hzn.className = "runs-c-hzn";
  hzn.dataset.odd = String(run.horizon_days !== 5);
  row.append(hzn);

  const anchor = el("span", "runs-c-num");
  anchor.append(renderFigure(run.anchor_spot));
  row.append(anchor);

  const close = el("span", "runs-c-num");
  if (isAbsent(run.outcome)) {
    close.append(el("span", "runs-c-open", "window open"));
  } else {
    close.append(renderFigure(run.outcome.close));
    close.append(chromeText(run.outcome.trading_date.slice(5), "the session the horizon closed on"));
    close.lastChild.className = "d";
  }
  row.append(close);

  const real = el("span", "runs-c-real");
  if (drifted) {
    // No realised figure on a re-based row: it would divide a split-adjusted
    // close by an unadjusted spot. The ratio is what there is.
    const r = el("span", "ratio");
    r.append(chromeText("×", "the ratio the snapshot moved by"), renderFigure(run.anchor_drift.ratio));
    real.append(r);
  } else if (isAbsent(run.outcome)) {
    real.append(el("span", "pending", "not yet"));
  } else {
    const fig = renderFigure(run.outcome.realised_log_return);
    fig.classList.add(run.outcome.realised_log_return.value >= 0 ? "up" : "down");
    real.append(fig);
  }
  row.append(real);

  row.addEventListener("click", () => ctx.onToggleRow(run.run_id));
  return row;
}

function detail(run, ctx) {
  const wrap = el("div", "runs-detail");

  const left = document.createElement("div");
  const tiles = el("div", "runs-tiles");
  for (const s of run.scenarios) {
    const t = el("div", "runs-tile");
    t.append(el("h4", null, s.name.replace(/_/g, " ")));
    const target = renderFigure(s.target_price);
    target.classList.add("target");
    t.append(target);
    const dl = el("dl");
    const pair = (k, fig) => { dl.append(el("dt", null, k)); const dd = el("dd"); dd.append(renderFigure(fig)); dl.append(dd); };
    pair("return", s.price_return);
    pair("vol", s.annualised_vol);
    pair("weight", s.probability_weight);
    t.append(dl);
    tiles.append(t);
  }
  left.append(tiles);
  const foot = el("div", "runs-tile-foot");
  foot.append(chromeText(run.run_id, "this run's full id"),
    document.createTextNode(run.document_is_frozen_exhibit ? " · read a frozen exhibit" : " · did not read a frozen exhibit"));
  left.append(foot);

  const says = el("div", "runs-says");
  const say = (label, tone) => {
    const s = el("div", "runs-say");
    if (tone) s.dataset.tone = tone;
    s.append(el("b", null, label));
    says.append(s);
    return s;
  };

  const rel = say("Relation");
  appendParts(rel, describeCorpusRelation(run));
  if (run.corpus_relation === "ledger_item") {
    rel.append(document.createTextNode(" Carried from the ledger, never derived from the anchor."));
  } else if (run.corpus_relation === "repeat_of_exhibit") {
    rel.append(document.createTextNode(
      " A frozen exhibit, but not the panel's run for it. Excluded from anything describing the " +
      "panel; its company page names the panel run it repeats."));
  } else if (run.corpus_relation === "outside_corpus") {
    rel.append(document.createTextNode(
      " Not part of the frozen corpus. The document this run read is not one the corpus holds."));
  }

  const drifted = !isAbsent(run.anchor_drift);
  const out = say("Outcome", isAbsent(run.outcome) ? "open" : null);
  if (isAbsent(run.outcome)) {
    out.append(document.createTextNode("The horizon has not elapsed yet — "));
    out.append(chromeText(`${run.horizon_days} sessions`, "the horizon in sessions"));
    out.append(document.createTextNode(
      " from this anchor land past the newest close the snapshot holds. There is no outcome, " +
      "and that is a fact about the calendar."));
  } else {
    appendParts(out, describeOutcome(run));
    if (!drifted) {
      out.append(document.createTextNode(" Realised "));
      out.append(renderFigure(run.outcome.realised_log_return));
      // The convention of the number ON SCREEN, not of the stored field.
      out.append(document.createTextNode(" — a log return, shown as the simple return it equals."));
    }
  }

  if (drifted) {
    const d = say("Re-based", "drift");
    appendParts(d, describeDrift(run));
    d.append(document.createTextNode(
      " No realised return is shown: it would mix two price bases."));
  }

  say("Score").append(document.createTextNode(
    "Cannot be computed for a run. Scoring keys on ticker and as_of, never run_id."));

  const fz = say("Freeze");
  if (isAbsent(run.freeze_version)) {
    fz.append(document.createTextNode(
      "Unrecorded. This run predates the field; it does not mean the run had no freeze."));
  } else {
    fz.append(document.createTextNode("Executed under frozen corpus "),
      chromeText(run.freeze_version, "the frozen corpus version this run executed under"),
      document.createTextNode("."));
  }

  wrap.append(left, says);
  return wrap;
}

function legend() {
  const box = el("div", "runs-legend");
  const item = (node, text) => {
    const s = document.createElement("span");
    s.append(node, document.createTextNode(text));
    box.append(s);
  };
  const sample = (prov) => {
    const f = renderFigure({ value: 302.98, provenance: prov, format: "price" });
    return f;
  };
  item(sample("measured"), " measured — read from the row");
  item(sample("derived"), " derived — computed on this page, weakest input wins");
  item(el("span", "swatch"), " re-based since the run");
  item(el("span", null, "unrecorded"), " freeze version predates the field — not “no freeze”");
  item(el("span", null, "realised"), " a log return, shown as the simple return it equals");
  return box;
}
