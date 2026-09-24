/* The holdout — its TERMS, and no score anywhere on the panel.

   The holdout was scored once, under ADR 0031. The per-item detail was printed
   once and never persisted, and `map evaluate --split holdout` is refused before
   anything is computed, so there is nothing to recover. What survives is the
   ledger row: the band, the item count, the dates, the code, and the correction
   the spend tested.

   EVERY NUMBER HERE COMES OUT OF THE SPEND RECORD. Not from the development
   records beside it, not from the README, not from a finding. The panel renders
   `holdout_spend.json` and stops. Findings #57's sentence about baselines is
   true and is not a holdout measurement, so it lives in the disclosure as prose
   and never as a figure on this card.

   THE COMMIT IS A REWRITTEN ONE. The spend was recorded at 9cb1b84, and a rebase
   on 8 September 2026 replayed that commit as 710879a; the original is now
   reachable only from refs/archive/pre-rebase-2026-09-08. The export carries
   what was recorded, which is right — the record is not edited after the fact —
   so the successor is looked up here, quoted, and shown as a second row rather
   than substituted for the first. */

import { CANNOT_BE_COMPUTED, isAbsent } from "../data/source.js";
import { DERIVED, MEASURED, chromeText, figure, renderFigure } from "../lib/figure.js";

/* QUOTED, AND NOT FROM THE EXPORT. Verified against the repository on
   2026-09-24: both commits carry the subject "Repoint the scoring vintage to the
   complete 2026-09-05 snapshot" and the same author date and patch-id; 9cb1b84
   is not an ancestor of main and is held only by refs/archive/pre-rebase-2026-09-08,
   and 710879a is. Abbreviations are the 7 characters this project uses
   everywhere; the record stores the full hash and is sliced before lookup. */
export const REWRITTEN = { "9cb1b84": "710879a" };
const REWRITE_EVENT = "the 8 September rebase";

const el = (tag, className, text) => {
  const n = document.createElement(tag);
  if (className) n.className = className;
  if (text !== undefined) n.textContent = text;
  return n;
};

export function renderHoldout(root, { holdout, pending }) {
  root.textContent = "";
  const card = el("section", "res-card res-holdout");
  const head = el("header");
  head.append(el("h2", null, "Holdout"));

  if (holdout && !isAbsent(holdout)) {
    head.append(chromeText(
      holdout.spends === 1 ? "spent once · terms exported, measurements not" : `spent ${holdout.spends} times · terms exported, measurements not`,
      "how many spends the ledger records",
    ));
  }
  card.append(head);

  if (!holdout) {
    card.append(waiting(pending));
    root.append(card);
    return card;
  }
  if (isAbsent(holdout)) {
    card.append(absence(holdout));
    root.append(card);
    return card;
  }

  const { spend } = holdout;
  card.append(headline(spend), correction(spend), terms(spend), noScores());
  root.append(card);
  return card;
}

/** The terms themselves were not exported, which is a different absence from
    "the scores were not exported" and is stated as itself. */
function absence(holdout) {
  const p = el("p", "res-absent");
  p.append(chromeText(holdout.why, "the export's own reason, verbatim; its digits are an ADR citation"));
  return p;
}

function headline(spend) {
  const h = el("p", "res-holdout-head");
  h.append(
    renderFigure(figure(spend.items, MEASURED, "int"), { className: "res-holdout-big" }),
    el("span", "res-headline-word", "items, scored once"),
  );
  return h;
}

function correction(spend) {
  const box = el("div", "res-holdout-form");
  box.append(el("div", "res-kicker", "Correction it tested"));

  const c = spend.calibration ?? {};
  const form = chromeText(c.form ?? "—", "the calibration form as the record states it");
  form.className = "res-holdout-formula";
  box.append(form);

  const coeffs = el("p", "res-holdout-coeffs");
  coeffs.append(
    el("span", "res-k", "a "),
    renderFigure(figure(c.a, MEASURED, "dec4")),
    el("span", "res-k", "  b "),
    renderFigure(figure(c.b, MEASURED, "dec4")),
  );
  box.append(coeffs);

  const on = el("p", "res-holdout-fitted");
  on.append(
    el("span", null, "fitted on "),
    chromeText(c.fitted_on ?? "—", "which population the coefficients were fitted on"),
  );
  box.append(on);
  return box;
}

function terms(spend) {
  const list = el("dl", "res-terms");
  const row = (key, node) => {
    list.append(el("dt", null, key));
    const dd = el("dd");
    dd.append(node);
    list.append(dd);
  };

  row("band", chromeText(spend.band, "which band the holdout spend covered"));
  row("scored", chromeText(spend.scored_on, "the day the single spend happened"));
  row("price vintage", chromeText(spend.price_vintage, "the pinned price snapshot it scored against"));
  row("freeze", chromeText(spend.freeze_version ?? "—", "the frozen corpus version"));

  /* Two rows, not one substitution. The record says 9cb1b84 and the record is
     right; the published history says 710879a. Showing only the successor would
     silently edit the ledger, and showing only the original would name a commit
     nobody can `git show`. */
  const recorded = (spend.commit ?? "").slice(0, 7);
  const successor = REWRITTEN[recorded];
  if (successor) {
    const now = el("span");
    now.append(
      chromeText(successor, "the commit in published history"),
      el("span", "res-terms-aside", " in published history"),
    );
    row("commit", now);
    const was = el("span", "res-terms-quoted");
    const aside = chromeText(`, replaced by ${REWRITE_EVENT}`, "when the rewrite happened");
    aside.className = "res-terms-aside";
    was.append(chromeText(recorded, "the commit the spend record stores"), aside);
    row("recorded as", was);
  } else if (recorded) {
    row("commit", chromeText(recorded, "the commit the spend record stores"));
  }

  const c = spend.calibration ?? {};
  const decided = el("span");
  decided.append(chromeText(
    [c.adr ? `ADR ${c.adr}` : null, ...(c.amended_by ?? [])].filter(Boolean).join(", amended by "),
    "the decisions that fixed these terms",
  ));
  row("decided in", decided);
  if (spend.prereg) row("pre-registered", chromeText(spend.prereg, "where the test was written down before the spend"));
  return list;
}

/** The last row, and the one the panel exists to make unmissable. */
function noScores() {
  const box = el("div", "res-no-scores");
  box.dataset.absence = CANNOT_BE_COMPUTED;
  box.append(
    el("span", "res-k", "Scores"),
    el("span", null, "none exist — never persisted, unrecoverable by design"),
  );
  return box;
}

/* The reading line carries a file size, so it is marked chrome with the reason.
   It is the one thing on the card before the record lands, and an unmarked
   number there fires the audit on the first paint of every load. */
function waiting(text) {
  const p = chromeText(text, "a progress line; its digits are a file size");
  p.className = "res-waiting";
  return p;
}
