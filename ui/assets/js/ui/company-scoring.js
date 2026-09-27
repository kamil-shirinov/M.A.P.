/* Section 6 — scoring, which never touches a run.

   A run carries its own forecast and its own outcome. A scoring record is a
   separate pass over a band and a split. They are related at band, split and
   vintage and at nothing finer, because the export provides no key joining them:
   a scored item's `as_of` is the forecast's own date and a run's `anchor_date` is
   the trading session it opened from, and those coincide only when the forecast
   date is itself a trading day — 161 of 175, missing 14.

   TWO RENDERINGS THIS SECTION REFUSES, and says so on the page rather than
   silently omitting. */

import { chromeText, figure, renderFigure, DERIVED, MEASURED } from "../lib/figure.js";

/** Four rows, mono, hairline-separated. Same wording as Results.

    Everything that argued rather than reported — why a score cannot attach to a
    run, what survives of the holdout, why the per-item detail is gone, and the
    two renderings this page refuses — is in the page-foot disclosure now. It
    was four paragraphs and a nested disclosure on a page that already runs to
    nine thousand pixels. */
export function renderScoring(root, { scoring, company }) {
  root.textContent = "";
  const h = document.createElement("h2");
  h.className = "cmp-h";
  h.append(document.createTextNode("Scoring"));
  const note = document.createElement("span");
  note.className = "section-note";
  note.textContent = "per band and split, never per run";
  h.append(note);
  root.append(h);

  const list = document.createElement("div");
  list.className = "cmp-score-rows";

  const identified = scoring.identifiable ?? [];
  const clean = identified.find((r) => r.band === "clean");
  const other = identified.find((r) => r.band !== "clean");

  if (clean) {
    list.append(scoreRow([
      chromeText(`${clean.band} · development · `, "the band and split this record covers"),
      renderFigure(figure(clean.n, MEASURED, "int")),
      chromeText(" items", "how many items were scored"),
      chromeText(` · code ${clean.forecast_digest.slice(0, 8)}`, "an abbreviated forecast digest"),
      chromeText(` · ${clean.vintage} vintage`, "the price vintage scored against"),
      chromeText(
        company.split === "dev"
          ? " · this company: in scope"
          : ` · this company: none in scope (${company.split})`,
        "whether this company's items are inside the record",
      ),
    ], "results.html"));
  }

  if (other) {
    list.append(scoreRow([
      chromeText(other.band, "the other band, scored as the leakage control"),
      chromeText(" · ", "a separator"),
      renderFigure(figure(other.n, MEASURED, "int")),
      chromeText(" items · separate record", "a different population, not more of the first"),
    ], "results.html"));
  }

  if (scoring.records.length > identified.length) {
    list.append(scoreRow([
      renderFigure(figure(scoring.records.length - identified.length, DERIVED, "int")),
      chromeText(" more clean record · same items · not shown, not averaged",
        "a second record of the same measurement under a different code state"),
    ], "results.html"));
  }

  list.append(holdoutRow(scoring.holdout));
  root.append(list);
}

/** One row. Ends with `results →` where the record it names is shown in full. */
function scoreRow(parts, href) {
  const row = document.createElement(href ? "a" : "div");
  row.className = "cmp-score-row";
  if (href) row.href = href;
  const body = document.createElement("span");
  body.className = "cmp-score-body";
  for (const part of parts) body.append(part);
  row.append(body);
  if (href) {
    const go = document.createElement("span");
    go.className = "cmp-score-go";
    go.textContent = "results →";
    row.append(go);
  }
  return row;
}

/** The holdout is a STATED FACT, not a pending state. Its terms survive and its
    scores do not, and the row says both rather than leaving a gap. */
function holdoutRow(entry) {
  if (!entry) return document.createDocumentFragment();
  const row = document.createElement("div");
  row.className = "cmp-score-row cmp-score-row--holdout";
  const body = document.createElement("span");
  body.className = "cmp-score-body";
  body.append(
    chromeText("holdout · ", "the split this row is about"),
    renderFigure(figure(173, MEASURED, "int")),
    chromeText(" items · scored once · terms in corpus/holdout_spend.json",
      "where the terms of the single spend survive"),
  );
  const scores = document.createElement("span");
  scores.className = "cmp-score-none";
  scores.textContent = "Scores: none exist — never persisted, unrecoverable by design";
  row.append(body, scores);
  return row;
}
