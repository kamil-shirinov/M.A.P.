/* THE data boundary. Nothing else in the app knows where data comes from.

   Reads the static export written by `map export` (see
   M.A.P./docs/export-contract.md). No server: these are flat files fetched from
   `assets/export/`, and a clone of this repository does not have them.

   Four rules this module exists to hold.

   ONE. Provenance is stamped HERE and never re-stamped downstream. A value read
   from the export is MEASURED; anything this module computes from measured
   inputs is DERIVED; a fixture is FABRICATED. `weakest` decides a combination,
   so provenance cannot be laundered through arithmetic — a price computed from a
   measured anchor and a measured return is derived, and says so.

   TWO. There is no unified return helper, and there must not be. The export
   carries two conventions under names that do not say so: a scenario's
   `price_return` is a SIMPLE return, and a scored item's `realised_return` is a
   LOG return. A single `applyReturn(spot, r)` is the hazard, because the two
   agree below about 4% and separate above it — a spot-check of typical values
   passes and the error appears on the large moves. So they are two functions
   with two names, and using the wrong one has to be a misspelling.

   THREE. Sentence builders return PARTS, never prose with a figure welded in.
   `lib/provenance-audit.js` has no heuristics by design, so a number inside a
   template string is a number the audit cannot see.

   FOUR. Absence has three kinds and they do not collapse. NOT_APPLICABLE (the
   question does not arise), NOT_COMPUTED (nobody asked), CANNOT_BE_COMPUTED (the
   answer does not exist and will not). The export makes all three distinctions
   and an interface that renders one empty state loses them.

   WHAT THIS MODULE DOES NOT EXPORT, and why. The five functions the fixture
   boundary offered — listUniverse, getHistory, getForecast, getTrackRecord,
   getCorpusReliability — are gone, because three of them cannot be answered from
   the export and answering them anyway would mean inventing data:

     getForecast      The export holds a LOG OF PAST RUNS, not a current
                      forecast. The newest anchor is 2026-08-13 and 777 of 779
                      horizons have already closed. `listRuns` returns runs, each
                      dated, and a caller decides what to show.
     getTrackRecord   Per-forecast PIT and an 80% band exist only inside a
                      scoring record — 175 items, clean/dev only — and cannot be
                      joined back to a run (see the note on `as_of` below).
     getCorpusReliability  No coverage rate is persisted anywhere. `map evaluate`
                      computes one and prints it; nothing writes it down.

   A JOIN THAT DOES NOT EXIST. A scored item carries `as_of`, the forecast's own
   date; a run carries `anchor_date`, the trading session it opened from. They
   coincide only when the forecast date is itself a trading day, so matching on
   them succeeds for 161 of 175 items and fails on 14 — Saturdays and Good Friday
   2026-04-03. That is the same shape as deriving `filing_date` from an anchor:
   right often enough to look right. This module therefore does not stitch scores
   onto runs, and exposes scoring records whole. */

import { DERIVED, FABRICATED, MEASURED, figure, weakest } from "../lib/figure.js";
import { inverseNormalCdf } from "../lib/gaussian.js";

const ROOT = "assets/export";

// --------------------------------------------------------------------------
// Absence
// --------------------------------------------------------------------------

/** The question does not arise for this record. Show nothing. */
export const NOT_APPLICABLE = "not-applicable";
/** Nobody asked — no input was supplied. NOT a negative answer. */
export const NOT_COMPUTED = "not-computed";
/** The answer does not exist and cannot be produced. State it. */
export const CANNOT_BE_COMPUTED = "cannot-be-computed";

export function absent(kind, why, extra = {}) {
  return { absent: kind, why, ...extra };
}

export const isAbsent = (v) => Boolean(v && v.absent);

// --------------------------------------------------------------------------
// The two return conventions
// --------------------------------------------------------------------------

/** A scenario's `price_return`. Simple: price = spot x (1 + r). */
export function priceFromSimpleReturn(spot, simpleReturn) {
  return spot * (1 + simpleReturn);
}

/** A scored item's `realised_return`. Log: price = spot x exp(r). */
export function priceFromLogReturn(spot, logReturn) {
  return spot * Math.exp(logReturn);
}

/** A log return as the simple return it corresponds to, for comparison with a
    scenario. The only sanctioned way to put the two side by side. */
export const simpleFromLog = (logReturn) => Math.expm1(logReturn);

/** A realised return computed from two measured closes. Log, to match the
    export's own `realised_return`, so a value this module derives and a value it
    reads are the same quantity. */
export const logReturnBetween = (from, to) => Math.log(to / from);

// --------------------------------------------------------------------------
// Fetching
// --------------------------------------------------------------------------

const cache = new Map();

async function readJson(path) {
  if (cache.has(path)) return cache.get(path);
  const promise = fetch(`${ROOT}/${path}`).then((response) => {
    if (response.status === 404) return null;
    if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
    return response.json();
  });
  cache.set(path, promise);
  return promise;
}

// --------------------------------------------------------------------------
// The boundary state
// --------------------------------------------------------------------------

/** No `manifest.json` at all. `assets/export/` is gitignored and generated, so
    this is what every clone of this repository sees until someone runs
    `map export`. Distinct from `partial`: there is nothing to read an absence
    FROM, so the export cannot state its own gaps and this module states them. */
export const NO_EXPORT = "no-export";
/** An export exists and named what it could not include. */
export const PARTIAL = "partial";
/** An export exists with no absences recorded. */
export const COMPLETE = "complete";

export async function getExportState() {
  const manifest = await readJson("manifest.json");
  if (manifest === null) {
    return {
      state: NO_EXPORT,
      manifest: null,
      absences: [],
      // The one absence the export cannot state for itself.
      why: absent(
        NOT_COMPUTED,
        "No export has been generated. `assets/export/` is gitignored: it is " +
          "produced by `map export` in the M.A.P. repository, not committed here.",
        { remedy: "uv run map export --out <this folder>/assets/export" },
      ),
    };
  }
  const absences = manifest.absent ?? [];
  return {
    state: absences.length ? PARTIAL : COMPLETE,
    manifest,
    absences,
    why: null,
  };
}

// --------------------------------------------------------------------------
// Companies and search
// --------------------------------------------------------------------------

/** The 120 companies the frozen corpus holds. Eager: it is 7.5 KB and every
    other view needs it. `exchange` is deliberately absent — it lives in the
    10,398-row symbol index, and loading 864 KB to label a row is the eager cost
    the export splits those two files to avoid. */
export async function listCorpusCompanies() {
  const rows = await readJson("universe.json");
  if (rows === null) return { rows: [], provenance: MEASURED, exportState: NO_EXPORT };
  return {
    rows: rows.map((row) => ({
      ticker: row.ticker,
      name: row.name ?? absent(NOT_COMPUTED, "the symbol index was not exported"),
      split: row.split,
      exchange: absent(NOT_COMPUTED, "listed in symbols.json; load it to resolve"),
    })),
    provenance: MEASURED,
  };
}

/** The full searchable index, lazily. 10,398 rows, 864 KB — fetch it on the
    first keystroke, not at boot. */
export async function searchSymbols(query, { limit = 20 } = {}) {
  const rows = await readJson("symbols.json");
  if (rows === null) return { rows: [], matched: 0, indexSize: null, provenance: MEASURED };
  const needle = query.trim().toUpperCase();
  // The index is open either way, so its size is knowable even for an empty
  // query. That is what lets the box stop saying "index not read".
  if (!needle) return { rows: [], matched: 0, indexSize: rows.length, provenance: MEASURED };
  const hits = rows.filter(
    (r) => r.ticker.startsWith(needle) || r.name.toUpperCase().includes(needle),
  );
  return {
    // `limit: Infinity` returns every hit, for a caller that groups them by
    // resolution before cutting each group.
    rows: limit === Infinity ? hits : hits.slice(0, limit),
    matched: hits.length,
    indexSize: rows.length,
    provenance: MEASURED,
  };
}

/** Filing and run counts per corpus company, from corpus.json.

    Separate from `listCorpusCompanies` on purpose. universe.json is 7.5 KB and
    every view needs it at boot; corpus.json is 108.8 KB and these counts are worth
    it exactly when a row that displays them is on screen. The search screen
    calls this on its first corpus hit.

    `runs` counts the runs the ledger maps to a company's filings. It is NOT
    `ledger.items_settled`, which is 709 across the corpus and counts completed
    runs and terminal failures together. */
export async function getCorpusFilingCounts() {
  const companies = await readJson("corpus.json");
  if (companies === null) return new Map();
  return new Map(
    companies.map((c) => [
      c.ticker,
      {
        filings: c.filings.length,
        runs: c.filings.reduce((n, f) => n + f.runs.length, 0),
      },
    ]),
  );
}

/** Whether a ticker's filer publishes earnings 8-Ks at all.

    `item_202_in_recent` reads only the submissions *recent* block — roughly a
    year for an active filer — so a company that stopped reporting three years ago
    answers `false`. That is a usable pre-screen and a false statement about
    history, which is why this returns the field under its own name and the
    sentence builder says "no recent earnings 8-K", never "never filed". */
export async function getFilerScreen(ticker) {
  const rows = await readJson("filers.json");
  if (rows === null) {
    return absent(NOT_COMPUTED, "the Item 2.02 pre-screen was not exported");
  }
  // Rows are append-only and a retry appends beside its failure, so the LAST row
  // for a filer wins.
  let latest = null;
  for (const row of rows) if (row.tickers.includes(ticker)) latest = row;
  if (latest === null) {
    return absent(NOT_APPLICABLE, `${ticker} is not in the SEC filer index`);
  }
  if (latest.status !== "ok") {
    return absent(NOT_COMPUTED, `the pre-screen could not read EDGAR for this filer`, {
      status: latest.status,
      fetched_on: latest.fetched_on,
    });
  }
  return {
    item_202_in_recent: latest.item_202_in_recent,
    count: figure(latest.count, MEASURED, "int"),
    most_recent: latest.most_recent,
    fetched_on: latest.fetched_on,
    provenance: MEASURED,
  };
}

// --------------------------------------------------------------------------
// One company: its filings, and the runs that read them
// --------------------------------------------------------------------------

/** Every filing the corpus holds for one company, each with the runs the ledger
    maps to it.

    A filing with an empty `runs` array is a held filing nothing ran — 8 of 709.
    It is returned, not dropped: a page showing only filings with runs shows 701
    and misstates the corpus. */
export async function getCompany(ticker) {
  const companies = await readJson("corpus.json");
  if (companies === null) {
    return absent(NOT_COMPUTED, "no export has been generated");
  }
  const row = companies.find((c) => c.ticker === ticker);
  if (!row) {
    return absent(NOT_APPLICABLE, `${ticker} is not in the frozen corpus`);
  }
  return {
    ticker: row.ticker,
    name: row.name,
    cik: row.cik,
    split: row.split,
    filings: row.filings.map((f) => ({
      // Carried, never derived. A corpus forecast is dated the day AFTER the
      // filing it reads, and only 66 of 701 have the two equal — reconstructing
      // this from a run's anchor is silently wrong on 635.
      filed: f.filed,
      accession: f.accession ?? absent(NOT_APPLICABLE, "this record predates accession storage"),
      band: f.band,
      split: f.split,
      run_ids: f.runs,
      ran: f.runs.length > 0,
    })),
    provenance: MEASURED,
  };
}

// --------------------------------------------------------------------------
// Runs
// --------------------------------------------------------------------------

export const SOURCES = ["corpus", "edgar", "news", "unknown"];

/** Runs for one company, KEPT APART by document source.

    Four files, four keys, no combined array — the separation the export writes
    is the separation the library enforces in memory, and flattening it here puts
    an out-of-corpus run one `.flat()` from a corpus figure. A caller that wants
    all of them iterates SOURCES deliberately.

    Rows arrive anchor-date descending and are not re-sorted. */
export async function listRuns(ticker) {
  const bySource = {};
  for (const name of SOURCES) {
    const rows = await readJson(`runs/by_source/${name}.json`);
    bySource[name] = (rows ?? []).filter((r) => r.ticker === ticker).map(adaptRun);
  }
  return { bySource, provenance: MEASURED };
}

/** The whole journal, still kept apart by source.

    `listRuns` answers "this company's runs"; this answers "every run", which is
    what a ledger screen draws. Same four keys and still no combined array: the
    caller that wants everything loops SOURCES itself, so the pooling is written
    where it can be seen rather than handed out pre-flattened.

    The four files together are 649.2 KB, almost all of it `unknown.json`. This
    is the one screen that opens them; the front door counts runs from the
    manifest instead. */
export async function listJournal() {
  const bySource = {};
  for (const name of SOURCES) {
    const rows = await readJson(`runs/by_source/${name}.json`);
    bySource[name] = (rows ?? []).map(adaptRun);
  }
  return { bySource, provenance: MEASURED };
}

/** Filings the corpus holds that no run ever read — 8 today, each a terminal
    failure the ledger settled. They are NOT runs and cannot be rows on a screen
    that counts runs; `ledger.items_settled` counts them and this does not.

    Computed from the file rather than carried: a hardcoded list goes stale the
    first time a corpus item settles. */
export async function listUnrunFilings() {
  const companies = await readJson("corpus.json");
  if (companies === null) return [];
  const out = [];
  for (const company of companies) {
    for (const filing of company.filings) {
      if (filing.runs.length) continue;
      out.push({
        ticker: company.ticker,
        filed: filing.filed,
        band: filing.band,
        split: filing.split ?? company.split,
      });
    }
  }
  return out;
}

function adaptRun(run) {
  const spot = run.anchor_spot;
  return {
    run_id: run.run_id,
    ticker: run.ticker,
    anchor_date: run.anchor_date,
    anchor_spot: figure(spot, MEASURED, "price"),
    horizon_days: run.horizon_days,

    // Scenario returns are SIMPLE. The target price is derived from two measured
    // inputs, so it is DERIVED and cannot be shown as a reading.
    scenarios: run.scenarios.map((s) => ({
      name: s.name,
      probability_weight: figure(s.probability_weight, MEASURED, "weight"),
      price_return: figure(s.price_return, MEASURED, "pct"),
      annualised_vol: figure(s.annualised_vol, MEASURED, "pct"),
      target_price: figure(priceFromSimpleReturn(spot, s.price_return), DERIVED, "price"),
    })),

    document_source: run.document_source,
    corpus_relation: run.corpus_relation,
    // Null means UNRECORDED, not "no freeze": 68 runs predate the field. An
    // absence says which, where a null rendered as a blank cell says neither.
    freeze_version: run.freeze_version ?? absent(NOT_COMPUTED, "this run predates the field"),
    document_is_frozen_exhibit: run.document_is_frozen_exhibit,
    arm: run.arm,
    // Present only when `corpus_relation` is "ledger_item".
    ledger_item: run.ledger_item ?? absent(NOT_APPLICABLE, "this run is not a panel item"),
    anchor_drift: run.anchor_drift
      ? {
          recorded_spot: figure(run.anchor_drift.recorded_spot, MEASURED, "price"),
          snapshot_close: figure(run.anchor_drift.snapshot_close, MEASURED, "price"),
          // Six places. The nine drifted rows carry seven distinct floats for two
          // corporate actions, so the raw value is not a key — group on ticker.
          ratio: figure(run.anchor_drift.ratio, MEASURED, "ratio"),
        }
      : absent(NOT_APPLICABLE, "the snapshot agrees with the price this run opened from"),
    outcome_status: run.outcome_status,
    outcome: adaptOutcome(run, spot),
  };
}

function adaptOutcome(run, spot) {
  if (run.outcome_status === "window_open") {
    return absent(NOT_APPLICABLE, "the horizon has not elapsed yet");
  }
  if (run.outcome_status === "absent_from_snapshot") {
    return absent(CANNOT_BE_COMPUTED, "the price snapshot holds no window covering this anchor");
  }
  if (run.outcome_status === "not_requested") {
    return absent(NOT_COMPUTED, "outcomes were not retrieved for this export");
  }
  const o = run.outcome;
  return {
    trading_date: o.trading_date,
    close: figure(o.close, MEASURED, "price"),
    // Derived from two measured closes, and LOG — the same quantity the export's
    // own `realised_return` is, so a read value and a computed one are comparable.
    realised_log_return: figure(logReturnBetween(spot, o.close), DERIVED, "logpct"),
    provider: o.provider,
    adjustment: o.adjustment,
    snapshot: o.snapshot,
    retrieved_on: o.retrieved_on,
    provenance: MEASURED,
  };
}

// --------------------------------------------------------------------------
// Prices
// --------------------------------------------------------------------------

/** One company's series, from the pinned snapshot. `[date, close]` pairs,
    ascending, closes only — there is no OHLC in the export.

    Not live prices. The newest value is a close on a trading date, so callers
    must label it "last close on <date>" and never "current". */
export async function getPriceSeries(ticker) {
  const series = await readJson(`prices/${ticker}.json`);
  if (series === null) {
    return absent(
      NOT_COMPUTED,
      `the ${ticker} series is not in this export — the snapshot held no window for it`,
    );
  }
  const last = series.bars.at(-1);
  return {
    ticker: series.ticker,
    sessions: series.bars,
    provider: series.provider,
    adjustment: series.adjustment,
    snapshot: series.snapshot,
    last_close: figure(last[1], MEASURED, "price"),
    last_close_date: last[0],
    provenance: MEASURED,
  };
}

// --------------------------------------------------------------------------
// Scores
// --------------------------------------------------------------------------

/** The scoring passes this export carries, newest-identifiable first.

    Prefer a record with a non-null `forecast_digest`: null means the pass ran
    from an uncommitted tree, so nothing names the code that produced it. Matching
    `manifest.code.forecast_digest` is NOT the test — a scoring pass is almost
    always older than the export shipping it, so equality essentially never holds
    and a consumer keying on it rejects every record. */
export async function listScoringRecords() {
  const { manifest, state } = await getExportState();
  if (state === NO_EXPORT) return { records: [], holdout: null, provenance: MEASURED };
  const records = [...(manifest.scores?.records ?? [])].sort(
    (a, b) => Number(Boolean(b.forecast_digest)) - Number(Boolean(a.forecast_digest)),
  );
  const identifiable = records.filter((r) => r.forecast_digest);
  return {
    records,
    identifiable,
    /* One record per band, and never an average of two.

       The clean band ships twice — the same 175 items scored from a committed
       tree and from a dirty one — and the two are one measurement recorded under
       two code states, not two results. `preferred` picks the identifiable one;
       `twins` names what was left out so a page can say it exists rather than
       quietly drop it. */
    preferred: bands(identifiable),
    twins: bands(records.filter((r) => !r.forecast_digest)),
    holdout: adaptHoldout(manifest.scores?.absent ?? []),
    provenance: MEASURED,
  };
}

/* The measurement first, then its control. The records sort digest-first and
   then by filename, which puts "ambiguous" before "clean" — fine for choosing a
   record, wrong for a control that reads left to right. */
const BAND_ORDER = ["clean", "ambiguous"];

/** First record per band, in reading order. */
function bands(records) {
  const out = new Map();
  for (const r of records) if (!out.has(r.band)) out.set(r.band, r);
  return new Map(
    [...out].sort((a, b) => {
      const rank = (n) => (BAND_ORDER.indexOf(n) + 1 || BAND_ORDER.length + 1);
      return rank(a[0]) - rank(b[0]) || (a[0] < b[0] ? -1 : 1);
    }),
  );
}

/** The holdout is a STATED FACT, not a pending state.

    It was scored once; the per-item detail was printed once and never persisted,
    and `map evaluate --split holdout` is refused before anything is computed. So
    this is CANNOT_BE_COMPUTED, and an interface must not render it as empty,
    loading, or a dash — that suggests a gap where there is a protection. */
function adaptHoldout(entries) {
  const entry = entries.find((e) => e.split === "holdout");
  if (!entry) return null;
  return absent(CANNOT_BE_COMPUTED, entry.reason, {
    split: entry.split,
    // Render from this, not from `why`. `why` explains what is gone; this says
    // what a reader can still go and look at, and is already a list.
    what_survives: entry.what_survives ?? [],
    survives_in: entry.survives_in,
  });
}

export async function getScoringRecord(file) {
  const record = await readJson(file);
  if (record === null) return absent(NOT_COMPUTED, `${file} is not in this export`);
  return {
    band: record.band,
    split: record.split,
    vintage: record.vintage,
    scored_on: record.scored_on,
    n: figure(record.n, MEASURED, "int"),
    unscored: record.unscored,
    // Rendered sentences, already written and already hedged. Display verbatim:
    // rewording them overstates the result.
    summaries: record.summaries,
    items: record.items,
    forecast_digest: record.forecast_digest,
    // Which code scored this pass, and which frozen corpus it scored. Not the
    // export's own commit: the export ships records older than itself, and the
    // footer's `code` stamp is a different fact from this one.
    commit: record.commit,
    freeze_version: record.freeze_version,
    freeze_digest: record.freeze_digest,
    file,
    provenance: MEASURED,
  };
}

/** The holdout's TERMS — the only thing that survived the one spend.

    Not its scores. `map evaluate --split holdout` is refused once the spend is
    recorded, the per-item detail was printed once and never persisted, and this
    file is the ledger row rather than a result. It is a LIST because the ledger
    is append-only; a second spend would append, and the last row is the current
    state. Today it holds one.

    The manifest points at the file through `absent[holdout].exported_as`. When
    that is null the terms were not exported and the absence is returned whole,
    with `spends` so a page can say the spend happened without the terms. */
export async function readHoldoutSpend() {
  const { manifest, state } = await getExportState();
  if (state === NO_EXPORT) return absent(NOT_COMPUTED, "no export has been generated");
  const entry = (manifest.scores?.absent ?? []).find((e) => e.split === "holdout");
  if (!entry) return absent(NOT_APPLICABLE, "this export records no holdout spend");
  if (!entry.exported_as) {
    return absent(CANNOT_BE_COMPUTED, entry.reason, { spends: entry.spends ?? null });
  }
  const rows = await readJson(entry.exported_as);
  if (rows === null || !rows.length) {
    return absent(NOT_COMPUTED, `${entry.exported_as} is named by the manifest but not in this export`);
  }
  return { spend: rows.at(-1), spends: rows.length, reason: entry.reason, provenance: MEASURED };
}

/** Everything the page computes from one record's items, worked out ONCE.

    Per-render recomputation of 175 items x four models is cheap enough not to
    show, which is exactly why it would never be noticed growing; and a band
    switch that recomputes is a band switch that can disagree with itself between
    two paints. Every field here is DERIVED — none of it is in the record.

    `z` IS Phi^-1(PIT), not realised/sigma. See lib/gaussian.js: the two differ
    (11 against 13 over 2.5 on the clean band) and this is the one the project's
    pre-registration names and published. */
export function scoreStatistics(items, { bins = 10 } = {}) {
  const n = items.length;
  const mean = (f) => items.reduce((t, i) => t + f(i), 0) / n;
  const rms = (f) => Math.sqrt(items.reduce((t, i) => t + f(i) ** 2, 0) / n);

  const pit = items.map((i) => i.map_pit);
  const histogram = new Array(bins).fill(0);
  // p === 1 lands in the last bin rather than in a bin that does not exist. It
  // is a real outcome — the close above every simulated path — not a rounding
  // artefact to drop.
  for (const p of pit) histogram[Math.min(Math.floor(p * bins), bins - 1)] += 1;

  /* z is undefined at the boundary. A PIT of exactly 0 or 1 means the outcome
     fell outside every simulated path, which is a real event and belongs in the
     histogram; it has no finite standardised distance, and clamping it to some
     large z would put a made-up number in a tail bucket. So those items are
     counted OUT of the tail statistics and counted separately, and the page
     names the shortfall rather than quietly reporting a smaller denominator.
     No item in the current export is at the boundary. */
  const standardisable = items.filter((i) => i.map_pit > 0 && i.map_pit < 1);
  const z = standardisable.map((i) => inverseNormalCdf(i.map_pit));
  const beyond = (t) => z.filter((v) => Math.abs(v) > t).length;
  const blocks = (t) =>
    new Set(standardisable.filter((_, k) => Math.abs(z[k]) > t).map((i) => Math.floor(i.day_index / 10))).size;

  const names = Object.keys(items[0].baseline_crps);
  const baseline = (key, name) => mean((i) => i[key][name]);

  return {
    n,
    tickers: new Set(items.map((i) => i.ticker)).size,
    dates: new Set(items.map((i) => i.as_of)).size,
    horizons: [...new Set(items.map((i) => i.horizon_days))],
    clusters: new Set(items.map((i) => Math.floor(i.day_index / 10))).size,
    histogram,
    bins,
    pitMean: mean((i) => i.map_pit),
    // RMS(stated sigma) over RMS(realised), the `k` of ADR 0018. Above 1.0 is
    // too wide, below is too narrow.
    calibrationRatio: rms((i) => i.map_sigma) / rms((i) => i.realised_return),
    tails: { 2.5: beyond(2.5), 3: beyond(3) },
    tailBlocks: { 2.5: blocks(2.5), 3: blocks(3) },
    // The denominator the tail counts are actually over, and the shortfall.
    zn: standardisable.length,
    zUndefined: n - standardisable.length,
    /* The OTHER definition — realised / sigma, which ignores where the forecast
       was centred. Not shown as a result: carried so the page can state the
       contrast for the band on screen. On the clean band the two give 13 and 11
       over 2.5; on the ambiguous band they agree at 11 and differ at 3. A page
       that quoted one band's pair while showing the other would be wrong half
       the time. */
    tailsIgnoringCentre: {
      2.5: items.filter((i) => Math.abs(i.realised_return / i.map_sigma) > 2.5).length,
      3: items.filter((i) => Math.abs(i.realised_return / i.map_sigma) > 3).length,
    },
    map: {
      crps: mean((i) => i.map_crps),
      log_score: mean((i) => i.map_log_score),
      brier: mean((i) => i.map_brier),
    },
    baselines: Object.fromEntries(
      names.map((name) => [name, {
        crps: baseline("baseline_crps", name),
        log_score: baseline("baseline_log_score", name),
        brier: baseline("baseline_brier", name),
      }]),
    ),
    /* Checked, not assumed. Every baseline scores exactly 0.25 on every item
       because each predicts a zero mean, so P(up) is 0.5 whatever the outcome —
       one comparison wearing three names. The page prints one row and says why;
       if this ever came back false the page would have to print three. */
    baselineBrierIsOneComparison: items.every((i) =>
      Object.values(i.baseline_brier).every((v) => v === 0.25)),
    directionRight: items.filter((i) => (i.map_probability_up > 0.5) === (i.realised_return > 0)).length,
    probabilityUp: {
      min: Math.min(...items.map((i) => i.map_probability_up)),
      max: Math.max(...items.map((i) => i.map_probability_up)),
    },
  };
}

// --------------------------------------------------------------------------
// Sentence builders — parts, never prose
// --------------------------------------------------------------------------

const text = (t) => ({ kind: "text", text: t });
const fig = (f) => ({ kind: "figure", figure: f });
/* A THIRD KIND, and it earns its place. A date is not a figure — it has no
   provenance to stamp — but it carries digits, and the audit has no heuristics,
   so it cannot sit in a plain text part either. Interpolating one into a
   template string is how `Closed at <fig> on 2026-08-20, retrieved 2026-09-09`
   put three unmarked dates on screen behind a correctly marked price. */
const chrome = (t, why) => ({ kind: "chrome", text: t, why });

/** What a run is to the pre-registered panel. Never the word "scored": a ledger
    entry promises artifacts exist, and no per-item score is persisted for any
    holdout item. */
export function describeCorpusRelation(run) {
  switch (run.corpus_relation) {
    case "ledger_item": {
      const item = run.ledger_item;
      if (isAbsent(item)) return [text("In the pre-registered panel.")];
      return [
        text(`In the pre-registered panel — ${item.band} band, filed `),
        chrome(item.filing_date, "the filing date, read from the ledger"),
        text("."),
      ];
    }
    case "repeat_of_exhibit":
      return [text("A frozen exhibit, but not the panel's run for it.")];
    case "outside_corpus":
      return [text("Not part of the frozen corpus.")];
    default:
      return [text("Not compared — this export has no frozen record or ledger.")];
  }
}

export function describeOutcome(run) {
  if (isAbsent(run.outcome)) return [text(run.outcome.why)];
  const o = run.outcome;
  return [
    text("Closed at "),
    fig(o.close),
    text(" on "),
    chrome(o.trading_date, "the session the horizon closed on"),
    text(", retrieved "),
    chrome(o.retrieved_on, "the day the close was read"),
    text(" from the "),
    chrome(o.snapshot, "the pinned price vintage it was read from"),
    text(" snapshot, "),
    // No digits, so plain text parts: the provider and the adjustment basis the
    // close was read on. `split_adjusted` is written as it reads aloud.
    text(`${o.provider}, ${o.adjustment.replace(/_/g, "-")}.`),
  ];
}

export function describeDrift(run) {
  if (isAbsent(run.anchor_drift)) return [];
  const d = run.anchor_drift;
  return [
    text("The price series has been re-based since this run: the snapshot closes "),
    fig(d.snapshot_close),
    text(" at this anchor against "),
    fig(d.recorded_spot),
    text(" recorded ("),
    fig(d.ratio),
    text("). This outcome is not part of any published score."),
  ];
}

/** `ledger.items_settled` is 709 and is NOT a run count: 701 completed plus 8
    that failed terminally, which is why 8 filings carry an empty run list. */
export function describeCorpusSize(manifest) {
  return [
    text("Corpus items settled: "),
    fig(figure(manifest.ledger.items_settled, MEASURED, "int")),
    text(" — completed runs and terminal failures together, not a count of forecasts."),
  ];
}

/** Runs per document source, from the manifest's `runs.rows` — one count per
    runs/by_source/ file, so "N runs" needs 1.9 KB rather than 649 KB.

    Four figures and deliberately no total: the export keeps the populations
    apart, and so does this boundary. A caller that wants a total adds them
    itself, where the pooling can be seen. An export older than 1.2.0 has no
    `runs.rows`, and that is stated rather than read as zero. */
export function runCountsBySource(manifest) {
  const rows = manifest?.runs?.rows;
  if (!rows || !SOURCES.every((s) => Number.isInteger(rows[s]))) {
    return absent(
      NOT_COMPUTED,
      "this export predates runs.rows (export_version 1.2.0); re-export to count runs without loading them",
    );
  }
  return Object.fromEntries(SOURCES.map((s) => [s, figure(rows[s], MEASURED, "int")]));
}

/** Whether the export carries a development scoring record. The one finding a
    page states in prose about baselines is backed by that file and by nothing
    else — the holdout's comparison was never persisted (M.A.P. Findings #57) —
    so without the record the finding has nothing under it and is not stated. */
export function devScoringRecordExported(manifest) {
  return (manifest?.scores?.records ?? []).some((r) => r.split === "dev");
}

// --------------------------------------------------------------------------
// Fixtures
// --------------------------------------------------------------------------

/** Anything still served from a fixture is stamped FABRICATED here, so the page
    banner and the chart watermark light up without a call site remembering to. */
export function fabricated(value, format = "int") {
  return figure(value, FABRICATED, format);
}

export { weakest, MEASURED, DERIVED, FABRICATED };
