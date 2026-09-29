/* Composition root for live analysis.

   THIS IS THE ONLY SCREEN THAT CAUSES ANYTHING TO EXIST. Every other page is a
   read of a static export. Here a press of Analyse runs three models locally for
   about seven minutes and writes a permanent entry to the run journal.

   Which means the page has two quite different states, and the difference is not
   cosmetic:

     with a server   `map serve` is running, `/analyse` answers, and the button
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
import { RELATIONS } from "./ui/runs-filters.js";
import { renderPageWhy } from "./ui/page-why.js";
import { renderFooter, renderMastheadVintage } from "./ui/company-footer.js";
import { applyPageProvenance, enforce } from "./lib/provenance-audit.js";
import { mountPageRosette } from "./ui/rosette.js";
import { mountMastheadNav } from "./ui/front-door.js";
import { chrome, chromeText } from "./lib/figure.js";
import {
  DEFAULT_HORIZON,
  PERIODS,
  noServerNotes,
  renderHorizons,
  renderNoServer,
  serverPresent,
} from "./ui/analyse-offer.js";

const $ = (id) => document.getElementById(id);

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

const state = { horizon: DEFAULT_HORIZON, running: false, started: null, typical: null };

/* What to expect, as a RANGE. A single median reads as a promise, and the middle
   eighty percent of the 701 recorded runs spans six to twelve minutes. The server
   measures both from `elapsed_s` in the ledger and sends them; this only formats
   whichever it was given. */
function range(event) {
  const mins = (s) => Math.round(s / 60);
  const span = event.usual_range_seconds;
  if (Array.isArray(span) && span.length === 2) {
    return `usually ${mins(span[0])} to ${mins(span[1])} minutes`;
  }
  return `usually about ${mins(event.typical_seconds)} minutes`;
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

  const periods = el("div", "anl-periods-host");
  renderHorizons(periods, {
    selected: state.horizon,
    onPick: (days) => { state.horizon = days; },
  });
  form.append(periods);

  const go = el("button", "anl-go", "Analyse");
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
      "locally, and writes a permanent entry to the run journal. It usually takes " +
      "six to twelve minutes and cannot be undone."),
    "what pressing Analyse does",
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
    const response = await fetch("analyse", {
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
      detail: range(event),
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
  /* The same tag the journal puts on a row, with the same words. A live run over
     a corpus company's latest filing IS a repeat — for AAPL today it is — and the
     screen has to say so rather than implying every live run reads something new. */
  const tag = el("span", "runs-tag tag",
    RELATIONS.find(([v]) => v === event.corpus_relation)?.[1] ?? event.corpus_relation);
  tag.dataset.rel = event.corpus_relation;
  head.append(chrome(tag, "how this run relates to the frozen corpus"));
  /* Both dates, because they are not always the same one. A run made before a
     session closes anchors on the previous close, so saying only "anchored
     2026-09-29" invites reading a 09-28 price as that day's.

     In ONE element: the head is a space-between row, and three children flung the
     price clause to the far margin where it read as an unrelated fragment. */
  const when = el("span", "anl-when");
  when.append(chromeText(`anchored ${event.anchor}`, "the date the run was made"));
  if (event.price_date && event.price_date !== event.anchor) {
    when.append(chromeText(
      ` · price is the ${event.price_date} close`,
      "the session the anchor price is the close of",
    ));
  } else if (event.price_date) {
    when.append(chromeText(" · at that day's close", "the session the anchor price is the close of"));
  }
  head.append(when);
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

/** A recorded run, drawn by the same view and labelled so it cannot read as live.

    No replayed progress and no elapsed counter: those would be theatre, and the
    whole posture of this project is against making a record look like an event.
    A banner, a date, and the result. */
async function renderReplay(host, banner) {
  const row = await source.getReplay();
  if (source.isAbsent(row)) {
    banner.textContent = "";
    return;
  }
  banner.textContent = "";
  const note = el("div", "anl-replay-note");
  note.append(chrome(el("strong", null, "A recorded run, not a live one."), "what this is"));
  note.append(chromeText(
    ` ${row.ticker} on ${row.anchor_date}, kept so this page shows what an analysis `
    + "produces. Nothing here was computed just now, and pressing Analyse above is "
    + "not possible on this copy.",
    "when the recorded run was made and why it is shown",
  ));
  banner.append(note);

  /* Rebuilt into the shape the result view takes. The scenarios are the run's own,
     off disk; the band is recomputed from them by the same mixture the scorer
     simulates, so it is reproducible from this repository without the models. */
  renderResult(host, {
    event: "result",
    run_id: row.run_id,
    ticker: row.ticker,
    anchor: row.anchor_date,
    price_date: row.anchor_date,
    spot: row.anchor_spot,
    horizon_days: row.horizon_days,
    corpus_relation: row.corpus_relation,
    scenarios: row.scenarios.map((s) => ({
      name: s.name,
      weight: s.probability_weight,
      price_return: s.price_return,
      annualised_vol: s.annualised_vol,
    })),
    band: bandFrom(row),
    marking: "uncalibrated",
    corrected: false,
    reasons: [
      "this is a recorded run, replayed from the export — the correction is "
      + "applied when a run is made, and this one was not eligible for it",
    ],
    correction: null,
  });
}

/** The band, from the run's own scenarios.

    A normal mixture sampled the way `mapf.eval.montecarlo` samples it, at the
    same seed, so the shaded region here is the one the scorer would score. Done
    in the browser because the alternative is the exporter shipping numbers the
    reader cannot check; these come from three weights and three volatilities that
    are printed on the same screen. */
function bandFrom(row) {
  const draws = [];
  let seed = 20260813;
  const rand = () => {
    // xorshift32, so the picture is the same on every visit and in every browser.
    seed ^= seed << 13; seed ^= seed >>> 17; seed ^= seed << 5;
    return ((seed >>> 0) % 1e6) / 1e6;
  };
  const gauss = () => {
    const u = Math.max(rand(), 1e-9);
    return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * rand());
  };
  const years = row.horizon_days / 252;
  for (const s of row.scenarios) {
    const n = Math.round(s.probability_weight * 20000);
    const drift = Math.log(1 + s.price_return);
    const vol = s.annualised_vol * Math.sqrt(years);
    for (let i = 0; i < n; i++) draws.push(drift - (vol * vol) / 2 + vol * gauss());
  }
  if (!draws.length) return [];
  draws.sort((a, b) => a - b);
  const at = (q) => draws[Math.min(draws.length - 1, Math.floor(q * draws.length))];
  return [0.1, 0.25, 0.75, 0.9].map((level) => ({
    level,
    price: row.anchor_spot * Math.exp(at(level)),
  }));
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
    /* A ticker in the URL is a handover from the search rows or a company page.
       It seeds the box and the horizon; it does NOT start a run. A link that
       spends seven minutes and writes a permanent journal entry on arrival would
       make the back button expensive. */
    const params = new URLSearchParams(location.search);
    const seeded = (params.get("ticker") ?? "").trim().toUpperCase();
    const horizon = Number(params.get("horizon"));
    if (PERIODS.some((p) => p.days === horizon)) state.horizon = horizon;
    renderAsk($("ask"));
    if (seeded) $("ask").querySelector(".anl-input").value = seeded;
  } else {
    renderNoServer($("ask"), {
      where: "This screen exists to run a forecast on demand.",
    });
    /* And then show one that already happened. A visitor who cannot run the
       models otherwise meets an absence where the most interesting screen should
       be, and never sees what the marking, the band or the relation tag look
       like. It is pinned in the exporter by run id, so this is the same run every
       time and never whatever was run locally most recently. */
    await renderReplay($("result"), $("progress"));
  }

  renderPageWhy($("why"), {
    groups: [...whyGroups(), ...((await serverPresent()) ? [] : [noServerNotes()])],
  });
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
