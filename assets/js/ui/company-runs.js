/* Section 5 — the journal's rows, for one company.

   THE SAME COMPONENT AS THE RUNS SCREEN, deliberately. These are the same runs
   the journal lists; showing them as eleven cards meant a reader comparing the
   two screens had to translate one shape into the other, and it let the two
   drift — the cards printed a realised return on a re-based run for months
   after the journal had stopped.

   Two columns are hidden rather than removed: company is constant here, and so
   is split, which the HOLDOUT tag in the page title already says. They are
   hidden in CSS so the row itself stays one thing.

   Rows arrive newest-anchor-first from the export and are NOT re-sorted. */

import { chromeText, figure, renderFigure, MEASURED } from "../lib/figure.js";
import { SOURCES, describeDrift, describeOutcome, isAbsent } from "../data/source.js";
import { COLUMNS, renderRowsInto } from "./runs-journal.js";

const RELATION = {
  ledger_item: { label: "panel item", why: "The ledger maps this run to a frozen corpus item." },
  repeat_of_exhibit: {
    label: "repeat",
    why: "Reads a frozen exhibit, but is not the panel's run for it.",
  },
  outside_corpus: { label: "outside corpus", why: "Its document is not one the corpus froze." },
  unchecked: { label: "not compared", why: "No frozen record or ledger reached this export." },
};

export function renderRuns(root, { runs, company, open, onToggle, universe }) {
  root.textContent = "";
  root.append(Object.assign(document.createElement("h2"), {
    className: "cmp-h", textContent: "Runs for this company",
  }));

  // Iterated per source deliberately. There is no combined array to flatten,
  // which is what keeps an out-of-corpus run out of a corpus figure.
  const rows = [];
  for (const name of SOURCES) rows.push(...runs.bySource[name]);

  const table = document.createElement("div");
  table.className = "runs-table runs-table--company";
  /* The universe map the row needs for names and splits. On this screen it is
     one company, and the row reads it the same way it does on the journal. */
  const one = universe ?? new Map([[company.ticker, { name: company.name, split: company.split }]]);
  renderRowsInto(table, {
    rows,
    ctx: { universe: one, openRows: open, onToggleRow: onToggle },
    columns: COLUMNS,
    // The one thing this screen knows that the journal does not: which panel run
    // a repeat is a repeat OF. It holds every run for the ticker; the journal
    // would have to scan all 779 to answer it.
    extra: (run) =>
      run.corpus_relation === "repeat_of_exhibit" ? panelRunBlock(run, company, rows) : null,
  });
  root.append(table);

  const legend = document.createElement("p");
  legend.className = "cmp-runs-legend";
  legend.append(
    chromeText(
      "outcomes yfinance, split-adjusted, " +
        `${sourceStamp(rows)} snapshot, retrieved ${retrievedStamp(rows)}`,
      "the price basis and the day the export read it, said once for the table",
    ),
  );
  root.append(legend);
}

/** Said once under the table rather than in every row. Read from the rows, not
    written into the copy: `retrieved_on` is the day the export ran and moves on
    every export. */
const sourceStamp = (rows) => stampOf(rows, (o) => o.snapshot) ?? "—";
const retrievedStamp = (rows) => stampOf(rows, (o) => o.retrieved_on) ?? "—";
function stampOf(rows, pick) {
  const seen = new Set();
  for (const run of rows) if (!isAbsent(run.outcome)) seen.add(pick(run.outcome));
  // More than one value means the table cannot say it once, so it says none.
  return seen.size === 1 ? [...seen][0] : null;
}

function card(run, company, open, onToggle, siblings) {
  const art = document.createElement("article");
  art.className = "cmp-card";
  art.dataset.relation = run.corpus_relation;

  const head = document.createElement("header");
  head.className = "cmp-card-head";
  head.append(
    chromeText(run.anchor_date, "the trading session this run opened from"),
    renderFigure(run.anchor_spot, { className: "cmp-anchor-spot" }),
    chromeText(`${run.horizon_days}-session horizon`, "the forecast horizon in sessions"),
  );

  const rel = document.createElement("span");
  rel.className = "cmp-relation";
  rel.textContent = RELATION[run.corpus_relation].label;

  /* ON EVERY CARD, not only where anchors collide. 62 (ticker, anchor, horizon)
     groups corpus-wide hold more than one run, so same-anchor pairs are common —
     but a field that appeared only on duplicates would be a signal a reader
     learns to scan for. Uniform placement makes it identity, which is what it
     is, and it is the key the disclosure state uses. */
  const right = document.createElement("div");
  right.className = "cmp-card-id";
  right.append(chromeText(run.run_id.slice(0, 8), "an abbreviated run id"), rel);
  head.append(right);
  art.append(head);

  const why = document.createElement("p");
  why.className = "cmp-why";
  why.textContent = RELATION[run.corpus_relation].why;
  art.append(why);

  if (run.corpus_relation === "ledger_item" && !isAbsent(run.ledger_item)) {
    const p = document.createElement("p");
    p.className = "cmp-why";
    p.append(
      document.createTextNode("Read the exhibit filed "),
      // CARRIED, never derived. Only 66 of 701 runs have filing_date equal to
      // their anchor, so reconstructing it would be wrong on 635.
      chromeText(run.ledger_item.filing_date, "the filing date, read from the ledger"),
      document.createTextNode(` · ${run.ledger_item.band} band.`),
    );
    art.append(p);
  }

  if (run.corpus_relation === "repeat_of_exhibit") art.append(panelRunBlock(run, company, siblings));

  art.append(disclosure(run, open, onToggle));
  art.append(outcomeBlock(run));
  const drift = driftBlock(run);
  if (drift) art.append(drift);
  return art;
}

/* ------------------------------------------------------------------ */
/* The three panel-run states                                          */
/* ------------------------------------------------------------------ */

function panelRunBlock(run, company, siblings) {
  /* A repeat's panel run is the LEDGER RUN AT THE SAME ANCHOR, not a filing found
     by date arithmetic. This resolved by `filing + 1 day`, which is right for 635
     of the 701 panel runs and wrong for the 66 whose anchor IS the filing date —
     TSLA's 2026-01-02 is one, so three of its repeats fell through to "(filing
     not identified)" and printed ATI's copy about a panel run that does not
     exist, while a9b0c9d8 sat in the filings table on the same page.

     Anchor matching resolves 73 of the 74 repeats. ATI's is the one true
     absence. */
  const panel = siblings.find(
    (r) => r.corpus_relation === "ledger_item" && r.anchor_date === run.anchor_date,
  ) ?? null;
  const filed = panel && !isAbsent(panel.ledger_item)
    ? panel.ledger_item.filing_date          // carried, never derived
    : filingNear(run, company);              // no panel run: the filing itself

  const box = document.createElement("div");
  box.className = panel ? "cmp-panel-link" : "cmp-panel-missing";

  if (panel) {
    // STATE 1 — linked, and the link is marked inferred.
    box.append(
      document.createTextNode("Read the exhibit filed "),
      chromeText(filed, "the filing date this repeat read, from the panel run's ledger entry"),
      document.createTextNode("; the panel's run is "),
      chromeText(panel.run_id.slice(0, 8), "the panel run's abbreviated id"),
      document.createTextNode(", anchored "),
      chromeText(run.anchor_date, "the anchor the pairing matched on"),
      document.createTextNode("."),
    );
    const tag = document.createElement("span");
    tag.className = "cmp-inferred";
    tag.textContent = "inferred link";
    box.append(" ", tag);

    const note = document.createElement("p");
    note.className = "cmp-subnote";
    // NO CORPUS-WIDE COUNT HERE. The spec's copy cites "73 of 74 repeats", but
    // this page loads one company's runs and cannot compute that -- it would be a
    // number typed into prose, which is the fabricated-figure hazard the whole
    // provenance scheme exists to catch. The qualitative claim carries the
    // meaning; the count belongs in the contract, where it is derived from all
    // 779 runs.
    note.textContent =
      "Matched on (ticker, anchor_date), not a key: source_doc_ids is not exported, " +
      "so nothing in the data states the two runs read the same document. It is " +
      "unambiguous throughout this export, and still inference. The panel's run is " +
      "the pre-registered one; this is not, and it is counted in nothing that " +
      "describes the panel.";
    box.append(note);
    return box;
  }

  // STATE 2 — the panel run does not exist. Not "exists but not shown here".
  box.append(
    document.createTextNode("Read the exhibit filed "),
    filed
      ? chromeText(filed, "the filing this repeat read")
      : document.createTextNode("(filing not identified)"),
    document.createTextNode(
      ", whose panel run does not exist: the corpus settled that filing as a " +
        "terminal failure, so nothing ever ran it. There is no link because there " +
        "is nothing to link to — not because a run exists and is shown elsewhere.",
    ),
  );
  return box;
}

/** The filing a repeat read, for the case where NO panel run exists to carry the
    date. Used only there: where a panel run exists its `ledger_item.filing_date`
    is carried and read directly.

    An anchor is the resolved trading session for a forecast dated the day after
    its filing, so it is the filing date or the next day — across all 701 panel
    runs it is one of those two and never anything else (66 and 635). Matching
    both is exhaustive; matching only `+1` is the bug this replaced. */
function filingNear(run, company) {
  const hit = company.filings.find(
    (f) => f.filed === run.anchor_date || nextDay(f.filed) === run.anchor_date,
  );
  return hit ? hit.filed : null;
}

function nextDay(iso) {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + 1);
  return d.toISOString().slice(0, 10);
}

/* ------------------------------------------------------------------ */
/* Scenarios, behind a per-run disclosure                              */
/* ------------------------------------------------------------------ */

function disclosure(run, open, onToggle) {
  const wrap = document.createElement("div");
  const isOpen = open.has(run.run_id);

  const button = document.createElement("button");
  button.type = "button";
  button.className = "cmp-disclose";
  button.setAttribute("aria-expanded", String(isOpen));
  button.textContent = isOpen ? "Hide scenarios" : "Show scenarios";
  // KEYED ON run_id. An anchor can repeat within a company and a filtered or
  // paginated ledger reorders freely, so an index-keyed open row would follow
  // the position rather than the run.
  button.addEventListener("click", () => onToggle(run.run_id));
  wrap.append(button);

  if (isOpen) wrap.append(scenarios(run));
  return wrap;
}

function scenarios(run) {
  const table = document.createElement("table");
  table.className = "cmp-scenarios";
  for (const s of run.scenarios) {
    const tr = document.createElement("tr");
    const name = document.createElement("td");
    name.textContent = s.name.replace("_", " ");
    tr.append(name);
    // price_return is a SIMPLE return and is formatted as one. A realised return
    // is a log return and never shares a helper with it.
    tr.append(td(renderFigure(s.probability_weight)));
    tr.append(td(renderFigure(s.price_return)));
    tr.append(td(renderFigure(s.annualised_vol)));
    tr.append(td(renderFigure(s.target_price)));
    table.append(tr);
  }
  return table;
}

/* ------------------------------------------------------------------ */
/* Outcome and drift                                                   */
/* ------------------------------------------------------------------ */

function outcomeBlock(run) {
  const p = document.createElement("p");
  p.className = "cmp-outcome";
  p.dataset.status = run.outcome_status;
  appendParts(p, describeOutcome(run));
  if (isAbsent(run.outcome)) return p;

  /* NO REALISED RETURN ON A RE-BASED RUN. The close is split-adjusted and the
     spot the run recorded is not, so the quotient is a number with two price
     bases in it. On AAPL's two 2026-08-13 runs it printed 2.7% — 311.30 over
     302.98 — which is neither the return the forecast was scored against nor
     any return that happened.

     The journal has always refused it and this page did not, so the same run
     read 2.7% on one screen and ×1.007509 on the other. The journal is right:
     what exists is the ratio, and it is in the re-based block below. */
  if (!isAbsent(run.anchor_drift)) {
    p.append(document.createTextNode(
      " No realised return is shown: it would mix two price bases."));
    return p;
  }

  p.append(
    document.createTextNode(" Realised "),
    renderFigure(run.outcome.realised_log_return),
    // NOT "(log)". The stored quantity is a log return; `fmt.logpct` applies
    // expm1 before printing, so the number on screen is the simple return that
    // log return equals. The label described the value in the field rather
    // than the one in front of the reader, which is the same error in the
    // other direction from sharing one helper between the two conventions.
    document.createTextNode(" — a log return, shown as the simple return it equals."),
  );
  return p;
}

function driftBlock(run) {
  const parts = describeDrift(run);
  if (!parts.length) return null;
  const box = document.createElement("div");
  box.className = "cmp-drift";
  appendParts(box, parts);
  const tail = document.createElement("p");
  tail.className = "cmp-subnote";
  tail.textContent =
    run.outcome_status === "closed"
      ? "Not part of any published score, and kept out of every figure that aggregates outcomes."
      : "Nothing to exclude yet; when the window closes it stays out.";
  box.append(tail);
  return box;
}

/** Sentence builders hand back parts, so a figure arrives as a marked node and
    never as text interpolated into a string the audit cannot see. */
function appendParts(host, parts) {
  for (const part of parts) {
    if (part.kind === "figure") host.append(renderFigure(part.figure));
    else if (part.kind === "chrome") host.append(chromeText(part.text, part.why));
    else host.append(document.createTextNode(part.text));
  }
}

function td(node) {
  const cell = document.createElement("td");
  cell.append(node);
  return cell;
}
