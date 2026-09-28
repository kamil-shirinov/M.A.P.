/* Composition root for live analysis.

   THIS IS THE ONLY SCREEN THAT CAUSES ANYTHING TO EXIST. Every other page is a
   read of a static export. Here a press of Analyze runs three models locally for
   about seven minutes and writes a permanent entry to the run journal.

   Which means the page has two quite different states, and the difference is not
   cosmetic:

     with a server   `map serve` is running, `/analyze` answers, and the button
                     does what it says.
     without one     these files are a static record. Nothing is queued, pending
                     or retrying, because there is nothing behind them to accept
                     a request. ONE stated absence says so (ADR 0036 §4) — not a
                     disabled control, which would assert dozens of times per
                     screen that the feature is temporarily unavailable.

   The period selector offers five, ten and twenty-one sessions. Ten and
   twenty-one are always uncalibrated: nothing was fitted at either, and the
   marking says so before the run starts rather than after it finishes. */

import * as source from "./data/source.js";
import { renderFan, renderMarking } from "./ui/analyse-fan.js";
import { renderPageWhy } from "./ui/page-why.js";
import { renderFooter, renderMastheadVintage } from "./ui/company-footer.js";
import { applyPageProvenance, enforce } from "./lib/provenance-audit.js";
import { mountPageRosette } from "./ui/rosette.js";
import { mountMastheadNav } from "./ui/front-door.js";
import { chrome, chromeText } from "./lib/figure.js";

const $ = (id) => document.getElementById(id);

/* The horizons this screen offers, and what each one is. Five is the only one
   anything was fitted at; the other two exist because a reader asking "and over
   a month?" deserves an answer that is marked rather than withheld. */
const PERIODS = [
  { days: 5, label: "5 sessions", note: "the fitted horizon" },
  { days: 10, label: "10 sessions", note: "uncalibrated" },
  { days: 21, label: "21 sessions", note: "uncalibrated" },
];

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

const state = { horizon: 5, running: false, started: null, typical: null };

/** Is there a server behind these files? One request, once, at boot.

    `/health` rather than a speculative POST: asking the question must not be
    able to start a run. */
async function serverPresent() {
  try {
    const response = await fetch("health", { method: "GET" });
    return response.ok;
  } catch {
    return false;
  }
}

/** The one stated absence. Replaces the whole interactive region rather than
    disabling parts of it. */
function renderAbsence(host) {
  host.textContent = "";
  const box = el("div", "cmp-empty");
  box.dataset.chrome = "no analysis server is present; nothing here is a figure";
  box.append(el("h1", null, "No analysis server"));
  box.append(el("p", null,
    "Live analysis runs three models on the machine serving this page, and these " +
    "files are a static record with nothing behind them. There is no queue and " +
    "nothing pending: the request cannot be made at all, rather than being made " +
    "and not answered."));
  box.append(el("p", null,
    "Everything already forecast is on the other screens, which are reads of an " +
    "export and need no server."));
  box.append(el("pre", null, "uv run map serve"));
  box.append(el("p", "anl-absence-foot",
    "That command serves this page and the endpoint from one origin, on your own " +
    "machine. Each analysis takes about seven minutes and is a permanent journal entry."));
  host.append(box);
}

function renderAsk(host) {
  host.textContent = "";
  const form = el("form", "anl-ask");

  const field = el("label", "anl-field");
  field.append(chrome(el("span", "anl-label", "Company"), "a form label"));
  const input = el("input", "anl-input");
  input.type = "search";
  input.name = "ticker";
  input.placeholder = "ticker";
  input.autocomplete = "off";
  input.spellcheck = false;
  input.required = true;
  field.append(input);
  form.append(field);

  const periods = el("fieldset", "anl-periods");
  periods.append(chrome(el("legend", null, "Horizon"), "a form label"));
  for (const period of PERIODS) {
    const wrap = el("label", "anl-period");
    const radio = el("input");
    radio.type = "radio";
    radio.name = "horizon";
    radio.value = String(period.days);
    radio.checked = period.days === state.horizon;
    radio.addEventListener("change", () => {
      state.horizon = period.days;
      renderAsk(host);
      host.querySelector(".anl-input").value = input.value;
    });
    wrap.append(radio);
    wrap.append(chromeText(period.label, "a horizon in trading sessions"));
    /* The marking is on the CONTROL, before anything runs. A reader choosing 21
       sessions should know it is uncalibrated while choosing it, not discover it
       from the result seven minutes later. */
    const note = el("span", "anl-period-note", period.note);
    if (period.days !== 5) note.dataset.calibration = "uncalibrated";
    wrap.append(chrome(note, "what this horizon is"));
    periods.append(wrap);
  }
  form.append(periods);

  const go = el("button", "anl-go", "Analyze");
  go.type = "submit";
  form.append(go);

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const ticker = input.value.trim().toUpperCase();
    if (ticker && !state.running) analyse(ticker, state.horizon);
  });

  host.append(form);
  host.append(chrome(
    el("p", "anl-cost",
      "One analysis reads the company's latest earnings 8-K, runs three models " +
      "locally, and writes a permanent entry to the run journal. It takes about " +
      "seven minutes and cannot be undone."),
    "what pressing Analyze does",
  ));
}

function renderProgress(host, lines) {
  host.textContent = "";
  if (!lines.length) return;
  const box = el("div", "anl-progress");
  for (const line of lines) {
    const row = el("div", "anl-step enter-row");
    row.append(chromeText(line.label, "a stage of the run"));
    if (line.detail) row.append(chromeText(` ${line.detail}`, "a note about the stage"));
    box.append(row);
  }
  host.append(box);
}

async function analyse(ticker, horizon) {
  state.running = true;
  state.started = Date.now();
  const lines = [];
  const progress = $("progress");
  const result = $("result");
  result.textContent = "";
  renderProgress(progress, [{ label: `Asking for ${ticker}…`, detail: "" }]);

  try {
    const response = await fetch("analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ticker, horizon_days: horizon }),
    });
    if (!response.ok) {
      const refusal = await response.json().catch(() => ({}));
      throw new Error(refusal.why ?? `the server refused with ${response.status}`);
    }
    /* Read as it arrives. The response is newline-delimited JSON precisely so the
       stages can be shown while the run is still going; buffering it would turn a
       progress display into a six-minute blank. */
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n");
      buffer = parts.pop() ?? "";
      for (const part of parts) {
        if (!part.trim()) continue;
        consume(JSON.parse(part), lines, progress, result);
      }
    }
  } catch (error) {
    lines.push({ label: "Stopped.", detail: String(error.message ?? error) });
    renderProgress(progress, lines);
  } finally {
    state.running = false;
  }
}

function consume(event, lines, progress, result) {
  if (event.event === "started") {
    state.typical = event.typical_seconds;
    lines.length = 0;
    lines.push({
      label: `Running ${event.ticker} over ${event.horizon_days} sessions.`,
      detail: `usually about ${Math.round(event.typical_seconds / 60)} minutes`,
    });
  } else if (event.event === "filing") {
    lines.push({ label: `Reading the 8-K filed ${event.filed}.`, detail: event.accession });
  } else if (event.event === "progress") {
    lines.push({ label: `${event.stage} finished.`, detail: event.detail });
  } else if (event.event === "failed") {
    lines.push({ label: "The run did not finish.", detail: event.why });
  } else if (event.event === "result") {
    lines.push({ label: "Done.", detail: "" });
    renderResult(result, event);
  }
  renderProgress(progress, lines);
  applyPageProvenance();
  enforce();
}

function renderResult(host, event) {
  host.textContent = "";
  const head = el("div", "anl-result-head");
  head.append(chrome(el("h3", null, `${event.ticker} · ${event.horizon_days} sessions`), "the run's subject"));
  head.append(chromeText(`anchored ${event.anchor}`, "the anchor date"));
  host.append(head);

  const marking = el("div", "anl-marking-host");
  // Marking first in the DOM, so a reader meets it before the picture.
  renderMarking(marking, event);
  host.append(marking);

  const chart = el("div", "anl-chart");
  renderFan(chart, event);
  host.append(chart);

  applyPageProvenance();
  enforce();
}

async function boot() {
  mountPageRosette($("ground"));
  mountMastheadNav($("masthead-nav"), { current: "analyse" });

  const exportState = await source.getExportState().catch(() => null);
  if (exportState?.manifest) {
    renderMastheadVintage($("masthead-vintage"), exportState.manifest);
    renderFooter($("footer"), exportState.manifest);
  }

  if (await serverPresent()) {
    renderAsk($("ask"));
  } else {
    renderAbsence($("ask"));
  }

  renderPageWhy($("why"), { groups: whyGroups() });
  applyPageProvenance();
  enforce();
}

export function whyGroups() {
  return [
    {
      title: "What a live analysis is",
      notes: [
        "The company's most recent 8-K Item 2.02 exhibit, read by three models running " +
          "on this machine. No hosted API is called and no data is sent to a model provider.",
        "It is a run, not a score. Nothing here is compared to an outcome, because the " +
          "outcome does not exist yet — the horizon has not elapsed.",
        "Every run is permanent. It lands in the journal, it is counted, and it is " +
          "exported. There is no discard.",
      ],
    },
    {
      title: "Why most fans are amber",
      meta: "ADR 0036",
      metaWhy: "the decision record this screen implements",
      notes: [
        "The fitted correction was measured on a panel: 175 development items at five " +
          "sessions, anchored within one trading day of the filing, from companies that " +
          "passed the corpus filters. Applying it anywhere else is extrapolation.",
        "So it is applied only where all three of those hold, and the fan is raw and " +
          "marked otherwise, with the failing condition named. The liquidity floor alone " +
          "is $50M median daily dollar volume, so a great many companies land here.",
        "A raw fan is not a neutral one. The uncorrected fan is the version measured too " +
          "narrow — calibration ratio 0.733 on development and 0.592 on the holdout, both " +
          "intervals excluding 1.0.",
        "Ten and twenty-one sessions are always uncalibrated. Nothing was fitted at either, " +
          "and the horizon control says so before the run rather than after it.",
      ],
    },
    {
      title: "What a corrected fan still does not claim",
      notes: [
        "That it is calibrated. The company is outside the frozen corpus, and the " +
          "correction's out-of-sample evidence is about the panel rather than about " +
          "arbitrary tickers. The three conditions make applying it defensible, not verified.",
      ],
    },
  ];
}

boot();
