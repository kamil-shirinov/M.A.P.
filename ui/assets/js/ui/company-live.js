/* Live runs, outside the record — the last section of every company page.

   ONE PAGE PER COMPANY (ADR 0036, amendment of 2026-09-30). A run is started from
   the page of the company it is about, and its progress and result appear here,
   under the record rather than on a screen of their own.

   THE SEPARATION IS THE SECTION. Everything above this heading is the record: the
   frozen corpus's filings, the runs the ledger maps to them, the scoring. Nothing
   in this section is part of it. Live runs are listed in their own table, counted
   in their own fact, never in a record count, and never drawn on the record's
   chart. That is ADR 0036's rule carried into layout.

   IT MUST NOT SAY WHICH FILING A RUN WILL READ. The page cannot know before the
   run which document EDGAR will return; for a corpus company it is often one of
   the filings above. The result carries the relation tag the journal gives it.

   With no server behind these files the page's one stated absence lands here
   (ADR 0036 §4). If the export's recorded run is this company's, it is shown
   under that absence, marked as recorded. */

import { chrome } from "../lib/figure.js";
import { fetchLiveRuns, serverPresent, streamAnalysis } from "../data/server.js";
import { PERIODS, DEFAULT_HORIZON, renderHorizons, renderNoServer } from "./analyse-offer.js";
import { COLUMNS, renderRowsInto } from "./runs-journal.js";
import { recordedNote, renderResult, replayAsResult } from "./live-result.js";
import { createProgress } from "./live-progress.js";
import { applyPageProvenance, enforce } from "../lib/provenance-audit.js";

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

/** Disclosure state for the live table, keyed on run id like the record's. */
const open = new Set();

/** The live rows a page should show: the server's journal when there is one,
    since it holds runs made after the last export; otherwise the export's.

    Read ONCE per page and handed to both the count at the top and the list here,
    so the two cannot disagree about how many there are. */
export async function liveRows(ticker, exportRows) {
  return ((await serverPresent()) ? await fetchLiveRuns(ticker) : null) ?? exportRows;
}

/**
    `rows`        this company's live runs, from `liveRows`
    `inCorpus`    whether the page above holds a record; changes one sentence
    `replay`      the export's recorded run, or an absence
    `horizon`     a horizon handed over by an old analyse link, if any
    `onRows`      told the new list after a run, so a count elsewhere can follow */
export async function renderLive(host, { ticker, name = null, rows = [], inCorpus, replay = null, horizon = null, onRows = null }) {
  host.textContent = "";
  const box = el("div", "cmp-live");
  box.append(chrome(el("h2", "cmp-h", "Live runs, outside the record"), "a section heading"));
  box.append(chrome(
    el("p", "cmp-live-rule",
      inCorpus
        ? "Forecasts made on demand, on this machine. None of them is part of the record " +
          "above: none is scored, none is counted there, and none is drawn on its chart."
        : "This company is outside the frozen corpus, so it has no record here — only " +
          "forecasts made on demand, on this machine. None is scored."),
    "how live runs relate to the record",
  ));

  const live = await serverPresent();
  const table = el("div", "cmp-live-runs");
  box.append(table);
  paintRows(table, rows, ticker, name);

  if (live) {
    const ask = el("div", "cmp-live-ask");
    const progress = el("div", "cmp-live-progress");
    const result = el("div", "cmp-live-result");
    box.append(ask, progress, result);
    host.append(box);
    renderAsk(ask, {
      ticker,
      horizon: PERIODS.some((p) => p.days === horizon) ? horizon : DEFAULT_HORIZON,
      onRun: (days) => run(ticker, days, { ask, progress, result, table, name, onRows }),
    });
    return box;
  }

  const absence = el("div", "cmp-live-absent");
  renderNoServer(absence, { where: `${ticker} cannot be run from this copy.` });
  box.append(absence);
  if (replay && !replay.absent && replay.ticker === ticker) {
    const result = el("div", "cmp-live-result");
    result.append(recordedNote(replay));
    const view = el("div");
    renderResult(view, replayAsResult(replay));
    result.append(view);
    box.append(result);
  }
  host.append(box);
  return box;
}

function paintRows(table, rows, ticker, name) {
  table.textContent = "";
  if (!rows.length) {
    table.append(chrome(el("p", "cmp-live-none", `No live run for ${ticker} yet.`), "a stated absence"));
    return;
  }
  const grid = el("div", "runs-table runs-table--company runs-table--live");
  renderRowsInto(grid, {
    rows,
    ctx: {
      universe: new Map([[ticker, { name, split: null }]]),
      openRows: open,
      onToggleRow: (runId) => {
        if (open.has(runId)) open.delete(runId);
        else open.add(runId);
        paintRows(table, rows, ticker, name);
        applyPageProvenance();
        enforce();
      },
    },
    columns: COLUMNS,
  });
  table.append(grid);
}

function renderAsk(host, { ticker, horizon, onRun }) {
  host.textContent = "";
  let chosen = horizon;
  const row = el("div", "cmp-live-row");
  const periods = el("div", "anl-periods-host");
  renderHorizons(periods, { name: "cmp-horizon", selected: chosen, onPick: (days) => { chosen = days; } });
  const go = el("button", "anl-go", "Analyse");
  go.type = "button";
  go.addEventListener("click", () => onRun(chosen));
  row.append(periods, chrome(go, "an action, not a measurement"));
  host.append(row);
  host.append(chrome(
    el("p", "anl-cost",
      `Reads ${ticker}'s most recent earnings 8-K, runs three models on this machine and ` +
      "writes a permanent entry to the run journal. That filing may be one of those above " +
      "or a newer one, and the result says which. It usually takes six to twelve minutes " +
      "and cannot be undone."),
    "what pressing Analyse does",
  ));
}

/* One run at a time per page. Not a disabled button: the control stays what it
   is, marked busy, and a second press while a run streams simply does nothing —
   the progress directly under it is the answer to "is something happening". */
let running = false;

async function run(ticker, horizon, { ask, progress, result, table, name, onRows }) {
  if (running) return;
  running = true;
  const go = ask.querySelector(".anl-go");
  go?.setAttribute("aria-busy", "true");
  result.textContent = "";
  const display = createProgress(progress, { ticker, horizon });
  await streamAnalysis(ticker, horizon, (event) => {
    display.update(event);
    if (event.event === "result") renderResult(result, event);
    applyPageProvenance();
    enforce();
  });
  display.finish();
  go?.removeAttribute("aria-busy");
  running = false;
  // The run just made is now in the journal; list it where it belongs.
  const rows = await fetchLiveRuns(ticker);
  if (rows) {
    paintRows(table, rows, ticker, name);
    onRows?.(rows);
  }
  applyPageProvenance();
  enforce();
}
