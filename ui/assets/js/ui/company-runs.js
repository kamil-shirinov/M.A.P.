/* Section 5 — one card per run. Cards only; there is no table branch.

   Max runs for any company is 16, median 6, min 4, so a collapse threshold never
   fires on this screen. The run ledger is a different screen with different
   volume and gets its own table there.

   Each card pairs a run's scenarios with its own outcome. That is the only
   honest pairing on the page: both come from the same row. A score does not
   appear on a card, and cannot — see the scoring section.

   Rows arrive newest-anchor-first from the export and are NOT re-sorted. */

import { chromeText, figure, renderFigure, MEASURED } from "../lib/figure.js";
import { SOURCES, describeDrift, describeOutcome, isAbsent } from "../data/source.js";

const RELATION = {
  ledger_item: { label: "panel item", why: "The ledger maps this run to a frozen corpus item." },
  repeat_of_exhibit: {
    label: "repeat",
    why: "Reads a frozen exhibit, but is not the panel's run for it.",
  },
  outside_corpus: { label: "outside corpus", why: "Its document is not one the corpus froze." },
  unchecked: { label: "not compared", why: "No frozen record or ledger reached this export." },
};

export function renderRuns(root, { runs, company, open, onToggle }) {
  root.textContent = "";
  root.append(Object.assign(document.createElement("h2"), {
    className: "cmp-h", textContent: "Runs for this company",
  }));

  // Iterated per source deliberately. There is no combined array to flatten,
  // which is what keeps an out-of-corpus run out of a corpus figure.
  const rows = [];
  for (const name of SOURCES) rows.push(...runs.bySource[name]);

  const list = document.createElement("div");
  list.className = "cmp-cards";
  for (const run of rows) list.append(card(run, company, open, onToggle));
  root.append(list);
}

function card(run, company, open, onToggle) {
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
  head.append(rel);
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

  if (run.corpus_relation === "repeat_of_exhibit") art.append(panelRunBlock(run, company));

  art.append(disclosure(run, open, onToggle));
  art.append(outcomeBlock(run));
  const drift = driftBlock(run);
  if (drift) art.append(drift);
  return art;
}

/* ------------------------------------------------------------------ */
/* The three panel-run states                                          */
/* ------------------------------------------------------------------ */

function panelRunBlock(run, company) {
  const filed = filingReadBy(run, company);
  const panel = filed && filed.ran ? filed : null;

  const box = document.createElement("div");
  box.className = panel ? "cmp-panel-link" : "cmp-panel-missing";

  if (panel) {
    // STATE 1 — linked, and the link is marked inferred.
    box.append(
      document.createTextNode("Read the exhibit filed "),
      chromeText(panel.filed, "the filing date this repeat read"),
      document.createTextNode("; a panel run is anchored "),
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
      ? chromeText(filed.filed, "the filing this repeat read")
      : document.createTextNode("(filing not identified)"),
    document.createTextNode(
      ", whose panel run does not exist: the corpus settled that filing as a " +
        "terminal failure, so nothing ever ran it. There is no link because there " +
        "is nothing to link to — not because a run exists and is shown elsewhere.",
    ),
  );
  return box;
}

/** The filing a repeat read, found the only way the export allows. A corpus run
    opens the day after the filing it reads. */
function filingReadBy(run, company) {
  return company.filings.find((f) => nextDay(f.filed) === run.anchor_date) ?? null;
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
  if (!isAbsent(run.outcome)) {
    p.append(
      document.createTextNode(" Realised "),
      renderFigure(run.outcome.realised_log_return),
      document.createTextNode(" (log)."),
    );
  }
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
