/* Section 6 — scoring, which never touches a run.

   A run carries its own forecast and its own outcome. A scoring record is a
   separate pass over a band and a split. They are related at band, split and
   vintage and at nothing finer, because the export provides no key joining them:
   a scored item's `as_of` is the forecast's own date and a run's `anchor_date` is
   the trading session it opened from, and those coincide only when the forecast
   date is itself a trading day — 161 of 175, missing 14.

   TWO RENDERINGS THIS SECTION REFUSES, and says so on the page rather than
   silently omitting. */

import { chrome, chromeText, figure, renderFigure, MEASURED } from "../lib/figure.js";
import { isAbsent } from "../data/source.js";

export function renderScoring(root, { scoring, company }) {
  root.textContent = "";
  root.append(Object.assign(document.createElement("h2"), {
    className: "cmp-h", textContent: "Scoring",
  }));

  const lead = document.createElement("p");
  lead.className = "cmp-standing";
  lead.textContent =
    "No score is attached to a run on this page, and none can be. A run carries its " +
    "own forecast and outcome; a scoring record is a separate pass over a band and a " +
    "split. They are related at band, split and vintage — never per item.";
  root.append(lead);

  root.append(devRecord(scoring, company));
  root.append(holdout(scoring.holdout));
  root.append(refusals());
}

function devRecord(scoring, company) {
  const box = document.createElement("div");
  box.className = "cmp-score";

  const identified = scoring.identifiable ?? [];
  if (!identified.length) {
    box.append(Object.assign(document.createElement("p"), {
      className: "cmp-absent",
      textContent: "No scoring record in this export names the code that produced it.",
    }));
    return box;
  }

  /* Prefer the record with a forecast_digest. A null digest means the pass ran
     from an uncommitted tree, so nothing identifies its code. The other record is
     the same measurement under a different code state, not a second result, and
     it is neither shown as one nor averaged in.

     And pick the CLEAN band by name. `identified[0]` was the whole selection
     while one band was scored; the ambiguous band's record now ships too and
     sorts first by filename, which would have put an ambiguous record under copy
     that says "its clean-band items are inside this record's scope". */
  const record = identified.find((r) => r.band === "clean") ?? identified[0];
  const h = document.createElement("h3");
  h.className = "cmp-h3";
  h.append(
    document.createTextNode("Development half · "),
    chromeText(`${record.band} band`, "which band was scored"),
    document.createTextNode(" · "),
    chromeText(`${record.vintage} vintage`, "the price vintage scored against"),
  );
  box.append(h);

  const p = document.createElement("p");
  p.append(
    document.createTextNode("One pass over "),
    renderFigure(figure(record.n, MEASURED, "int")),
    document.createTextNode(" items corpus-wide, under code "),
    chromeText(record.forecast_digest.slice(0, 8), "an abbreviated forecast digest"),
    document.createTextNode("."),
  );
  box.append(p);

  const scope = document.createElement("p");
  scope.className = "cmp-subnote";
  scope.append(
    document.createTextNode("This company is in the "),
    chromeText(company.split, "which half of the panel this company is in"),
    document.createTextNode(
      company.split === "dev"
        ? " half, so its clean-band items are inside this record's scope."
        : " half, so none of its items are inside this record's scope — the record covers the development half only.",
    ),
  );
  box.append(scope);

  // The other band, when it is scored: a different population, not more of this one.
  const control = identified.find((r) => r.band !== record.band);
  if (control) {
    const note = document.createElement("p");
    note.className = "cmp-subnote";
    note.append(
      document.createTextNode("The "),
      chromeText(`${control.band} band`, "the other band, scored as the leakage control"),
      document.createTextNode(" is scored separately, over "),
      renderFigure(figure(control.n, MEASURED, "int")),
      document.createTextNode(
        " items — the training-cutoff control, a different population and not part of " +
          "this record.",
      ),
    );
    box.append(note);
  }

  if (scoring.records.length > identified.length) {
    const other = document.createElement("p");
    other.className = "cmp-subnote";
    other.textContent =
      "A second record for the same items ships from an unidentifiable tree — the " +
      "same measurement recorded twice under different code states, not two results. " +
      "It is not shown here and not averaged in.";
    box.append(other);
  }
  return box;
}

/** A STATED FACT, not a pending state. Rendered from `what_survives`, which says
    what a reader can still go and look at; `reason` explains what is gone and is
    the disclosure behind it. Never an empty state, a spinner or a dash. */
function holdout(entry) {
  const box = document.createElement("div");
  box.className = "cmp-score cmp-score--holdout";
  if (!entry) return box;

  box.append(Object.assign(document.createElement("h3"), {
    className: "cmp-h3", textContent: "Holdout — scored once",
  }));

  const list = document.createElement("ul");
  list.className = "cmp-survives";
  for (const line of entry.what_survives) {
    const li = document.createElement("li");
    li.textContent = line;
    list.append(li);
  }
  box.append(
    Object.assign(document.createElement("p"), {
      textContent: "What survives, and where:",
    }),
    list,
  );

  const where = document.createElement("p");
  where.className = "cmp-subnote";
  where.append(chromeText(entry.survives_in, "a filename and a note about it"));
  box.append(where);

  const why = document.createElement("details");
  why.className = "cmp-disclosure";
  const sum = document.createElement("summary");
  sum.textContent = "Why the per-item detail is gone";
  const body = document.createElement("p");
  body.textContent = entry.why;
  // The reason cites ADR 0031. Every digit in it is a citation, not a quantity,
  // and the audit has no heuristics to tell those apart.
  chrome(body, "explanatory prose; its digits are an ADR citation");
  why.append(sum, body);
  box.append(why);

  const not = document.createElement("p");
  not.className = "cmp-subnote";
  not.textContent = "Nothing is coming later. This is not an empty state.";
  box.append(not);
  return box;
}

function refusals() {
  const box = document.createElement("div");
  box.className = "cmp-refusals";
  box.append(Object.assign(document.createElement("h3"), {
    className: "cmp-h3", textContent: "Two renderings this page refuses",
  }));

  const ul = document.createElement("ul");
  for (const [title, body] of [
    [
      "“Not scored.”",
      "The record covers one band and one split. Most panel runs sit outside its " +
        "scope legitimately — the ambiguous band and the whole holdout were never in " +
        "it. Printing the negative would claim that scored-eligible runs went unscored.",
    ],
    [
      "A reconstructed band.",
      "Scored items carry map_sigma but no p10, p50 or p90. Building a band from " +
        "sigma is modelling presented as reading. The percentiles do not exist, so " +
        "the column does not either.",
    ],
  ]) {
    const li = document.createElement("li");
    const strong = document.createElement("strong");
    strong.textContent = title;
    li.append(strong, document.createTextNode(" " + body));
    // "p10, p50 or p90" are field names. Same reason as above.
    chrome(li, "explanatory prose; its digits are field names");
    ul.append(li);
  }
  box.append(ul);
  return box;
}
