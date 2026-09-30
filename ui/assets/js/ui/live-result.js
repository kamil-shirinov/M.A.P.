/* One live run's result, drawn where it was asked for: on the company's page.

   Moved here from the retired live-analysis screen, unchanged in what it says.
   The marking is rendered before the fan in the DOM, so a reader meets what the
   fan is before the picture of it, and `renderFan` still refuses a result that
   carries no marking at all (ADR 0036 §1). */

import { renderFan, renderMarking } from "./analyse-fan.js";
import { RELATIONS } from "./runs-filters.js";
import { chrome, chromeText } from "../lib/figure.js";

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

/** The result view: a head naming the run, the marking, then the fan. */
export function renderResult(host, event, { opening = true } = {}) {
  host.textContent = "";
  const head = el("div", "anl-result-head");
  head.append(chrome(el("h3", null, `${event.ticker} · ${event.horizon_days} sessions`), "the run's subject"));
  /* The same tag the journal puts on a row, with the same words. A live run over
     a corpus company's latest filing IS a repeat, and the view has to say so
     rather than implying every live run reads something new. */
  const tag = el("span", "runs-tag tag",
    RELATIONS.find(([v]) => v === event.corpus_relation)?.[1] ?? event.corpus_relation);
  tag.dataset.rel = event.corpus_relation;
  head.append(chrome(tag, "how this run relates to the frozen corpus"));
  head.append(whenClause(event));
  host.append(head);

  const marking = el("div", "anl-marking-host");
  renderMarking(marking, event);
  host.append(marking);

  const chart = el("div", "anl-chart");
  renderFan(chart, event, { opening });
  host.append(chart);
  return host;
}

/** Both dates, because they are not always the same one, in ONE element.

    A run made before a session settles anchors on the previous close, so the
    run's own date and its price's date differ; a run made mid-session anchors
    on a quote that is not a close at all, and says so (Findings #64). */
function whenClause(event) {
  const when = el("span", "anl-when");
  when.append(chromeText(`anchored ${event.anchor}`, "the date the run was made"));
  if (event.price_date && event.price_date !== event.anchor) {
    when.append(chromeText(
      ` · price is the ${event.price_date} close`,
      "the session the anchor price is the close of",
    ));
  } else if (event.price_kind === "intraday") {
    const at = (event.price_taken_at ?? "").slice(11, 16);
    when.append(chromeText(
      ` · price taken during that session${at ? `, ${at} UTC` : ""} — not a close`,
      "the anchor price was an intraday quote, not a settled close",
    ));
  } else if (event.price_date) {
    when.append(chromeText(" · at that day's close", "the session the anchor price is the close of"));
  }
  return when;
}

/** A recorded run, in the shape the result view takes.

    The scenarios are the run's own, off disk; the fan and the band were computed
    by `map export` from the same `simulate()` the scorer runs, so the picture is
    reproducible from this repository without the models. */
export function replayAsResult(row) {
  return {
    event: "result",
    run_id: row.run_id,
    ticker: row.ticker,
    anchor: row.anchor_date,
    price_date: row.anchor_date,
    price_kind: row.price_kind,
    price_taken_at: row.price_taken_at,
    spot: row.anchor_spot,
    horizon_days: row.horizon_days,
    corpus_relation: row.corpus_relation,
    scenarios: row.scenarios.map((s) => ({
      name: s.name,
      weight: s.probability_weight,
      price_return: s.price_return,
      annualised_vol: s.annualised_vol,
    })),
    band: row.band ?? [],
    fan: row.fan ?? null,
    history: row.history ?? null,
    marking: "uncalibrated",
    corrected: false,
    reasons: [
      "this is a recorded run, replayed from the export — the correction is "
      + "applied when a run is made, and this one was not eligible for it",
    ],
    correction: null,
  };
}

/** The line that stops a recorded run reading as live. No replayed progress and
    no elapsed counter: those would be theatre. A statement, a date, the result. */
export function recordedNote(row) {
  const note = el("div", "anl-replay-note");
  note.append(chrome(el("strong", null, "A recorded run, not a live one."), "what this is"));
  note.append(chromeText(
    ` ${row.ticker} on ${row.anchor_date}, kept so this copy shows what an analysis `
    + "produces. Nothing here was computed just now.",
    "when the recorded run was made and why it is shown",
  ));
  return note;
}
