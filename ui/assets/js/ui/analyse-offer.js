/* Offering an analysis, wherever it is offered from.

   Three screens can start one — the search rows, a company page, and the live
   analysis screen itself — and all three need the same three things: to know
   whether a server is there, to let a reader pick a horizon, and to say the same
   thing when there is no server. One module, so those three answers cannot drift
   apart between screens.

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

let probe = null;

/** Is a server behind these files? One GET, once per page load.

    `health` rather than a speculative POST: asking the question must never be
    able to start a run, because a run costs seven minutes and is permanent. */
export function serverPresent() {
  probe ??= fetch("health", { method: "GET" })
    .then((response) => response.ok)
    .catch(() => false);
  return probe;
}

/** For tests: forget the memoised answer. */
export function resetProbe() {
  probe = null;
}

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
  box.append(el("p", null,
    `${where} Live analysis runs three models on the machine serving this page, and ` +
    "these files are a static record with nothing behind them."));
  box.append(el("p", null,
    "Nothing is queued and nothing is pending: the request cannot be made at all, " +
    "rather than being made and not answered."));
  box.append(el("pre", null, "uv run map serve"));
  box.append(el("p", "anl-absent-foot",
    "That serves this page and the endpoint from one origin, on your own machine. " +
    "Each analysis takes about seven minutes and is a permanent journal entry."));
  host.append(box);
  return box;
}

/** A link into the live-analysis screen, carrying a ticker and a horizon.

    A LINK, not a button that posts from here. The run belongs to the screen built
    to show one: that screen owns the progress display, the marking and the fan,
    and starting a seven-minute run from a search row would leave the reader on a
    page with nowhere to put the answer. */
export function analyseLink(ticker, { horizon = DEFAULT_HORIZON, label = "Analyse" } = {}) {
  const link = el("a", "anl-offer", label);
  link.href = `analyse.html?ticker=${encodeURIComponent(ticker)}&horizon=${horizon}`;
  link.title = `Run a forecast for ${ticker} on this machine`;
  return chrome(link, "an action, not a measurement");
}
