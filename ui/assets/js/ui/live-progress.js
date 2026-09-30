/* A run in progress, reported from the run's own trace.

   Each line is an event the server read off `trace.jsonl` or the EDGAR lookup. A
   stage is shown finished because the run recorded it, never because enough
   seconds passed. */

import { chromeText } from "../lib/figure.js";

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

/* What to expect, as a RANGE. A single median reads as a promise, and the middle
   eighty percent of recorded runs spans six to twelve minutes. The server
   measures both from `elapsed_s` in the ledger and sends them. */
export function expected(event) {
  const mins = (s) => Math.round(s / 60);
  const span = event.usual_range_seconds;
  if (Array.isArray(span) && span.length === 2) {
    return `usually ${mins(span[0])} to ${mins(span[1])} minutes`;
  }
  return `usually about ${mins(event.typical_seconds)} minutes`;
}

export function createProgress(host, { ticker }) {
  const lines = [{ label: `Asking for ${ticker}…`, detail: "" }];
  const paint = () => {
    host.textContent = "";
    const box = el("div", "anl-progress");
    for (const line of lines) {
      const row = el("div", "anl-step");
      row.append(chromeText(line.label, "a stage of the run"));
      if (line.detail) row.append(chromeText(` ${line.detail}`, "a note about the stage"));
      box.append(row);
    }
    host.append(box);
  };
  paint();
  return {
    update(event) {
      if (event.event === "started") {
        lines.length = 0;
        lines.push({
          label: `Running ${event.ticker} over ${event.horizon_days} sessions.`,
          detail: expected(event),
        });
      } else if (event.event === "filing") {
        lines.push({ label: `Reading the 8-K filed ${event.filed}.`, detail: event.accession });
      } else if (event.event === "progress") {
        lines.push({ label: `${event.stage} finished.`, detail: event.detail });
      } else if (event.event === "failed") {
        lines.push({ label: "The run did not finish.", detail: event.why });
      } else if (event.event === "result") {
        lines.push({ label: "Done.", detail: "" });
      }
      paint();
    },
    finish() {},
  };
}
