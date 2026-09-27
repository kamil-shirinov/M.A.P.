/* Composition root for the results screen.

   WHAT LOADS WHEN.

     manifest.json          2.2 KB, eager — record identity, n per band, sizes,
                            and `scores.absent`, which is what points at the
                            holdout's terms. Every stamp in the header is true
                            from this alone.
     the two records      133.5 KB each, in parallel — the clean one with a
                            forecast digest and the ambiguous one. Fetched
                            together because the leakage control needs both at
                            once and always shows both, whatever band is selected.
     holdout_spend.json     0.4 KB — named by the manifest, never assumed.

   THE THIRD CLEAN RECORD IS NEVER FETCHED. It has a null forecast_digest: the
   same 175 items scored from an uncommitted tree. The manifest names it, the
   header says it exists, and 133.5 KB is not spent on a measurement the screen
   has already said it will not show.

   NOT LOADED AT ALL: the journal (649.2 KB), the universe, prices, symbols,
   filers. Nothing on this screen is per-company or per-run, and the screen that
   is has its own page.

   STATISTICS ARE WORKED OUT ONCE PER RECORD, at the moment it lands, not per
   render. A band switch repaints; it does not re-read 175 items four times. */

import * as source from "./data/source.js";
import { applyPageProvenance, enforce } from "./lib/provenance-audit.js";
import { fmt } from "./lib/format.js";
import { mountPageRosette } from "./ui/rosette.js";
import { mountMastheadNav } from "./ui/front-door.js";
import { renderFooter, renderMastheadVintage } from "./ui/company-footer.js";
import { renderIdentity } from "./ui/results-identity.js";
import { renderPit } from "./ui/results-pit.js";
import { domainFor, renderBaselines } from "./ui/results-baselines.js";
import { renderLeakage } from "./ui/results-leakage.js";
import { renderDirection } from "./ui/results-direction.js";
import { renderHoldout } from "./ui/results-holdout.js";
import { whyGroups } from "./ui/results-disclosure.js";
import { renderPageWhy } from "./ui/page-why.js";
import { renderNoExport } from "./ui/no-export.js";

const $ = (id) => document.getElementById(id);

const RULES = ["crps", "log score"];

const state = {
  stage: "reading",
  error: null,
  manifest: null,
  records: null,
  /** band -> { record, stats } */
  loaded: new Map(),
  holdout: null,
  band: "clean",
  bins: 10,
};

/** The axis domain for each rule, over BOTH records, so switching band moves the
    points and never the scale. Recomputed as records land and then fixed. */
function domains() {
  const both = [...state.loaded.values()].map((e) => ({ stats: e.stats, summaries: e.record.summaries }));
  return Object.fromEntries(RULES.map((key) => [key, domainFor(both, ruleOf(key))]));
}

const ruleOf = (key) => ({ key, field: key === "crps" ? "crps" : "log_score" });

const shown = () => state.loaded.get(state.band) ?? null;

function paint() {
  if (state.stage === "no-export") {
    renderNoExport($("results-page"), state.error, {
      footer: $("footer"), vintage: $("masthead-vintage"),
    });
    applyPageProvenance();
    enforce();
    return;
  }

  if (state.stage === "no-records") {
    renderNoRecords();
    applyPageProvenance();
    enforce();
    return;
  }

  const here = shown();
  const meta = state.records?.preferred.get(state.band);
  const waiting = `Reading the ${state.band} record — ${fmt.kb(sizeOf(meta))}…`;

  if (meta) {
    renderIdentity($("res-identity"), {
      meta,
      record: here?.record ?? null,
      stats: here?.stats ?? null,
      records: state.records,
      band: state.band,
      onBand: (band) => { state.band = band; paint(); },
    });
  }

  renderPit($("pit"), { stats: here?.stats ?? null, pending: waiting });
  renderBaselines($("baselines"), {
    stats: here?.stats ?? null,
    summaries: here?.record.summaries ?? null,
    domains: domains(),
    pending: waiting,
  });
  renderLeakage($("leakage"), {
    clean: state.loaded.get("clean")?.stats ?? null,
    ambiguous: state.loaded.get("ambiguous")?.stats ?? null,
    pending: "Reading both records — the control needs each band's mean CRPS…",
  });
  renderDirection($("direction"), {
    stats: here?.stats ?? null,
    items: here?.record.items ?? [],
    pending: waiting,
  });
  renderHoldout($("holdout"), { holdout: state.holdout, pending: "Reading the holdout's terms…" });
  renderPageWhy($("disclosure"), {
    groups: whyGroups({
      holdoutReason: state.records?.holdout?.why ?? null,
      stats: here?.stats ?? null,
      band: state.band,
    }),
  });
  if (state.manifest) renderResultsFooter(here?.record ?? null);

  renderStatus(
    state.stage === "failed" ? `Could not read the export: ${state.error}`
      : state.stage === "reading" ? waiting
      : null,
  );

  applyPageProvenance();
  enforce();
}

const sizeOf = (meta) => state.manifest?.files?.[meta?.file] ?? 0;

/** Shown only while reading or on failure. A status line that is always there
    is furniture; one that appears is information. */
function renderStatus(text) {
  const host = $("status");
  host.textContent = "";
  host.dataset.on = String(Boolean(text));
  if (!text) return;
  const p = document.createElement("p");
  p.className = "res-status";
  // It carries a file size and a band name, neither of which is a measurement.
  p.dataset.chrome = "a progress or failure line; its digits are a file size";
  p.textContent = text;
  host.append(p);
}

function renderLegend() {
  const host = $("legend");
  host.textContent = "";
  const dl = document.createElement("dl");
  dl.className = "res-legend";
  for (const [key, what] of [
    ["measured", "read from a scoring record or the spend ledger"],
    ["derived", "computed on this page from those values"],
    ["quoted", "stated elsewhere and repeated here — never recomputed"],
  ]) {
    const dt = document.createElement("dt");
    dt.className = `res-legend-key res-legend-key--${key}`;
    /* A SAMPLE of the stroke, not a swatch of colour. The three marks are
       plain, dotted and dashed underlines; a legend that named them without
       showing one is a legend a reader has to take on trust. The sample carries
       the real `data-prov`, so it is drawn by the same rule the figures are. */
    const sample = document.createElement("span");
    sample.className = "res-legend-sample";
    sample.dataset.prov = key;
    sample.dataset.chrome = "a sample of the mark this word names";
    sample.textContent = "0.000";
    dt.append(sample, document.createTextNode(` ${key}`));
    const dd = document.createElement("dd");
    dd.textContent = what;
    dl.append(dt, dd);
  }
  host.append(dl);
}

/** One record, adapted and measured, at the moment it arrives. */
async function take(band, meta) {
  const record = await source.getScoringRecord(meta.file);
  if (source.isAbsent(record)) throw new Error(record.why);
  state.loaded.set(band, { record, stats: source.scoreStatistics(record.items, { bins: state.bins }) });
}

async function boot() {
  mountPageRosette($("ground"));
  mountMastheadNav($("masthead-nav"), { current: "results" });

  const params = new URLSearchParams(location.search);
  if (params.get("band") === "ambiguous") state.band = "ambiguous";
  if (params.get("bins") === "20") state.bins = 20;

  const exportState = await source.getExportState();
  if (exportState.state === source.NO_EXPORT) {
    state.stage = "no-export";
    // The absence itself, not its message: the panel prints the reason AND the
    // command that fixes it.
    state.error = exportState.why;
    paint();
    return;
  }
  state.manifest = exportState.manifest;
  state.records = await source.listScoringRecords();

  /* AN EXPORT WITH NO SCORING RECORD IN IT. `map export --allow-partial` on a
     clone produces exactly this, and it is what a newcomer gets.

     Before this the page fell straight through: `Promise.all([])` resolves at
     once, the stage went to `ready` with nothing loaded, and every figure sat on
     its pending "…" forever — with the status line hidden, because the page
     believed it had finished. A reader saw eight ellipses and no explanation.

     The export states this absence itself, so the page prints its words. */
  if (state.records.preferred.size === 0) {
    state.stage = "no-records";
    state.error = (state.manifest.absent ?? []).find((a) => a.what === "scores") ?? null;
    renderMastheadVintage($("masthead-vintage"), state.manifest);
    paint();
    return;
  }

  if (!state.records.preferred.has(state.band)) {
    state.band = [...state.records.preferred.keys()][0] ?? state.band;
  }
  renderMastheadVintage($("masthead-vintage"), state.manifest);
  renderLegend();
  paint();

  try {
    // Both records at once. The leakage control shows both bands whatever the
    // switch says, so there is no band the page can defer.
    await Promise.all(
      [...state.records.preferred].map(([band, meta]) => take(band, meta)),
    );
    state.holdout = await source.readHoldoutSpend();
    state.stage = "ready";
  } catch (err) {
    state.stage = "failed";
    state.error = String(err.message ?? err);
  }

  paint();
}

/** The export exists and carries no scoring pass.

    Distinct from NO EXPORT, which is a missing directory, and said differently:
    the export is here, it named this gap itself, and the page repeats its words
    rather than inventing a second explanation. Every panel below the head is
    removed rather than left showing "…", because there is nothing coming. */
function renderNoRecords() {
  const main = $("results-page");
  for (const id of ["res-identity", "pit", "baselines", "leakage", "direction", "holdout"]) {
    const host = $(id);
    if (host) host.textContent = "";
  }
  for (const row of main.querySelectorAll(".res-row-1, .res-row-2")) row.remove();

  const box = document.createElement("div");
  box.className = "cmp-empty res-absent-page";
  box.dataset.chrome = "a stated absence; its digits are a path";
  const h = document.createElement("h2");
  h.className = "section-h";
  h.textContent = "No scoring pass in this export";
  const p = document.createElement("p");
  p.textContent = state.error?.reason
    ? `${state.error.reason} — nothing has been scored, so there is no result to show.`
    : "This export carries no scoring record, so there is no result to show.";
  const where = document.createElement("p");
  where.className = "cmp-note";
  where.textContent = state.error?.path
    ? `Scoring passes are written to ${state.error.path} by \`map evaluate\`, and exported from there.`
    : "Scoring passes are written by `map evaluate` and exported from there.";
  box.append(h, p, where);
  $("res-identity").append(box);

  renderFooter($("footer"), state.manifest);
  renderPageWhy($("disclosure"), {
    groups: whyGroups({ holdoutReason: state.records?.holdout?.why ?? null, stats: null, band: state.band }),
  });
  renderStatus(null);
}

/** The shared footer plus one stamp of this screen's own.

    `code` in the shared footer is the EXPORT's commit. `scored` is the day the
    record ON SCREEN was scored, which is a different fact about a different
    pass — the clean record was scored on 2026-09-09 by 83370f6 and the export
    was written on 2026-09-24 by bfbf92e. Rebuilt on every paint, because the
    band switch changes which record it describes. */
function renderResultsFooter(record) {
  const host = $("footer");
  renderFooter(host, state.manifest);
  if (!record) return;
  const stamps = [...host.children].find((n) => n.className?.includes?.("cmp-stamps"));
  if (!stamps) return;
  const span = document.createElement("span");
  span.dataset.chrome = "the day the record on screen was scored";
  span.textContent = `scored ${record.scored_on}`;
  stamps.append(span);
}

boot();
