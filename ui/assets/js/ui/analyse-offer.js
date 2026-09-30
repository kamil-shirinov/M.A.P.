/* Offering an analysis, wherever it is offered from.

   One screen starts a run now — the company page, for the company the run is
   about (ADR 0036, amendment of 2026-09-30). This module still holds the three
   things that screen needs, so they are written once: whether a server is
   there, the horizon choice, and the same sentence when there is no server.

   THE PROBE RUNS ONCE PER PAGE. `serverPresent()` memoises its promise, so a
   screen with forty rows asks once rather than forty times, and a row never
   becomes the thing that decides whether the feature exists.

   ADR 0036 §4 is the shape of the no-server case: ONE stated absence per page,
   never a disabled control per row. A disabled button asserts, once per row,
   that the feature is temporarily unavailable — and it is not. There is nothing
   behind these files to accept the request, so nothing is queued or pending. */

import { chrome, chromeText } from "../lib/figure.js";

/* Five is the only horizon anything was fitted at. Ten and twenty-one are
   offered because a reader asking "and over a month?" deserves an answer that is
   marked rather than withheld — and they are marked HERE, on the control, so the
   marking is read while choosing rather than six minutes later. */
export const PERIODS = [
  { days: 5, label: "5 sessions", note: "the fitted horizon" },
  { days: 10, label: "10 sessions", note: "uncalibrated" },
  { days: 21, label: "21 sessions", note: "uncalibrated" },
];

export const DEFAULT_HORIZON = 5;

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

/* One probe per page, owned by the module that owns every server call. Re-exported
   so the screens that already ask here keep one answer between them. */
export { resetProbe, serverPresent } from "../data/server.js";

/** The horizon control, shared by every screen that offers a run.

    `onPick` receives the number of sessions. The marking is applied to the note
    beside each label, using the same `data-calibration` attribute the fan and the
    company page use, so one rule in one stylesheet colours all of them. */
export function renderHorizons(host, { selected = DEFAULT_HORIZON, onPick, name = "horizon" } = {}) {
  host.textContent = "";
  const box = el("fieldset", "anl-periods");
  box.append(chrome(el("legend", null, "Horizon"), "a form label"));
  for (const period of PERIODS) {
    const wrap = el("label", "anl-period");
    const radio = el("input");
    radio.type = "radio";
    radio.name = name;
    radio.value = String(period.days);
    radio.checked = period.days === selected;
    radio.addEventListener("change", () => onPick?.(period.days));
    wrap.append(radio);
    wrap.append(chromeText(period.label, "a horizon in trading sessions"));
    const note = el("span", "anl-period-note", period.note);
    if (period.days !== DEFAULT_HORIZON) note.dataset.calibration = "uncalibrated";
    wrap.append(chrome(note, "what this horizon is"));
    box.append(wrap);
  }
  host.append(box);
  return box;
}

/** The one stated absence, in the same words on every screen that offers a run.

    `where` names what this particular screen would otherwise have offered, so
    the sentence is about this page rather than a generic notice repeated three
    times. Everything after it is identical by construction. */
export function renderNoServer(host, { where }) {
  host.textContent = "";
  const box = el("div", "anl-absent");
  box.dataset.chrome = "no analysis server is present; nothing here is a figure";
  box.append(el("h3", "anl-absent-head", "No analysis server"));
  /* ONE LINE. It was four paragraphs, which is a wall of prose on a screen whose
     job at that moment is to say one thing. The reasoning — why nothing is
     queued, what the command does, what a run costs — is worth having and now
     lives in the disclosure with the other notes, where a reader goes when they
     want it rather than meeting it on the way past. */
  box.append(el("p", null,
    `${where} Live analysis runs on the machine that has the models; this copy is a ` +
    "static record."));
  host.append(box);
  return box;
}

/** The notes this component contributes to a page's disclosure.

    Everything the box used to say on screen. Merged into each page's own groups
    so there is one disclosure per screen rather than a second one below it. */
export function noServerNotes() {
  return {
    title: "Why there is no Analyse button here",
    notes: [
      "Live analysis reads a company's latest earnings 8-K and runs three models over " +
        "it. The models run on the machine serving the page, so a published copy of " +
        "this site — which is a directory of static files — cannot do it.",
      "Nothing is queued and nothing is pending. There is no server behind these files " +
        "to accept the request, so it is not made at all rather than made and unanswered.",
      "On your own machine, `uv run map serve` serves this page and the endpoint from " +
        "one origin. Each analysis usually takes six to twelve minutes and writes a " +
        "permanent entry to the run journal; there is no discard.",
    ],
  };
}
