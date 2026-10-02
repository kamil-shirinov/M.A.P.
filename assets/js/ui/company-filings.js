/* Section 4 — every filing the corpus holds for this company.

   INCLUDING THE ONES NOTHING RAN. 8 of 709 filings corpus-wide have an empty
   `runs[]` — terminal failures — and they are rows here, not omissions. A table
   that showed only filings with runs would show 701 and misstate the record it
   is drawing from. */

import { chromeText } from "../lib/figure.js";
import { isAbsent } from "../data/source.js";
import { stagger } from "../lib/motion.js";

const COLUMNS = ["Filed", "Band", "Accession", "Panel run"];

export function renderFilings(root, { company, runs }) {
  root.textContent = "";
  root.append(Object.assign(document.createElement("h2"), {
    className: "cmp-h", textContent: "Filings the corpus holds",
  }));

  const rows = Object.values(runs.bySource).flatMap((r) => r);
  const repeats = rows.filter((r) => r.corpus_relation === "repeat_of_exhibit");

  const table = document.createElement("table");
  table.className = "cmp-table";
  const thead = document.createElement("thead");
  const hr = document.createElement("tr");
  for (const c of COLUMNS) {
    const th = document.createElement("th");
    th.textContent = c;
    hr.append(th);
  }
  thead.append(hr);
  table.append(thead);

  const tbody = document.createElement("tbody");
  const entering = company.filings.map((filing) => filingRow(filing, repeats));
  entering.forEach((row) => tbody.append(row));
  stagger(entering);
  table.append(tbody);
  root.append(table);
  root.append(bandNote());
}

function filingRow(filing, repeats) {
  const tr = document.createElement("tr");

  tr.append(cell(chromeText(filing.filed, "the date the 8-K was filed")));

  // clean = after the training cutoff; ambiguous = before it, and it measures
  // leakage. A factual partition, so both read neutral — amber belongs to the
  // missing-panel-run rule and to the uncalibrated state, neither of which is a
  // property of a band.
  const band = document.createElement("span");
  band.className = "cmp-band";
  band.textContent = filing.band;
  tr.append(cell(band));

  tr.append(cell(
    isAbsent(filing.accession)
      ? Object.assign(document.createElement("em"), {
          className: "cmp-absent", textContent: "predates accession storage",
        })
      : chromeText(filing.accession, "an SEC accession number, not a quantity"),
  ));

  tr.append(cell(panelRunCell(filing, repeats)));
  if (!filing.ran) tr.classList.add("cmp-row--unrun");
  return tr;
}

/** Mirrors the third panel-run state. A filing settled without a run reads
    "held, not run", and if a repeat read its exhibit that is a sub-note — the
    cross-link stays one-directional, so the repeat points here and this does not
    point back at the repeat. */
function panelRunCell(filing, repeats) {
  const wrap = document.createElement("div");
  if (filing.ran) {
    wrap.append(chromeText(filing.run_ids[0].slice(0, 8), "a run id, abbreviated"));
    return wrap;
  }
  const label = document.createElement("span");
  label.className = "cmp-unrun";
  label.textContent = "held, not run";
  wrap.append(label);

  // Same window as company-runs.js: an anchor is the filing date or the next
  // day, never anything else across all 701 panel runs. Matching only `+1` missed
  // the 66 where they coincide.
  const readBy = repeats.some(
    (r) => r.anchor_date === filing.filed || nextDay(filing.filed) === r.anchor_date,
  );
  if (readBy) {
    const note = document.createElement("div");
    note.className = "cmp-subnote";
    note.textContent = "a repeat read this exhibit";
    wrap.append(note);
  }
  return wrap;
}

/** Used ONLY to spot a repeat that read an unrun filing, and only alongside an
    exact-date match — never to produce a filing_date, which is carried on
    `ledger_item`. The 66 of 701 runs whose anchor IS the filing date are exactly
    the ones a `+1`-only rule gets wrong. */
function nextDay(iso) {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + 1);
  return d.toISOString().slice(0, 10);
}

/** One mono legend line. What the two band words mean is a legend; that neither
    is the good half is an argument, and arguments are in the disclosure. */
function bandNote() {
  const p = document.createElement("p");
  p.className = "cmp-legend";
  p.textContent =
    "clean after the models' training cutoff · ambiguous before it; measures leakage";
  return p;
}

function cell(node) {
  const td = document.createElement("td");
  td.append(node);
  return td;
}
