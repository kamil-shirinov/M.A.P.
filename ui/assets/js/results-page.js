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
import { mountRosette } from "./ui/rosette.js";
import { mountMastheadNav } from "./ui/front-door.js";
import { renderFooter, renderMastheadVintage } from "./ui/company-footer.js";
import { renderIdentity } from "./ui/results-identity.js";
import { renderPit } from "./ui/results-pit.js";
import { domainFor, renderBaselines } from "./ui/results-baselines.js";
import { renderLeakage } from "./ui/results-leakage.js";
import { renderDirection } from "./ui/results-direction.js";
import { renderHoldout } from "./ui/results-holdout.js";
import { renderDisclosure } from "./ui/results-disclosure.js";

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
    renderStatus(state.error);
    applyPageProvenance();
    enforce();
    return;
  }

  const here = shown();
  const meta = state.records?.preferred.get(state.band);
  const waiting = `Reading the ${state.band} record — ${fmt.kb(sizeOf(meta))}…`;

  if (meta) {
    renderIdentity($("identity"), {
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
  renderDisclosure($("disclosure"), {
    holdoutReason: state.records?.holdout?.why ?? null,
    stats: here?.stats ?? null,
    band: state.band,
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
    dt.textContent = key;
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
  mountRosette($("ground"));
  mountMastheadNav($("masthead-nav"), { current: "results" });

  const params = new URLSearchParams(location.search);
  if (params.get("band") === "ambiguous") state.band = "ambiguous";
  if (params.get("bins") === "20") state.bins = 20;

  const exportState = await source.getExportState();
  if (exportState.state === source.NO_EXPORT) {
    state.stage = "no-export";
    state.error = exportState.why.why;
    paint();
    return;
  }
  state.manifest = exportState.manifest;
  state.records = await source.listScoringRecords();
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
