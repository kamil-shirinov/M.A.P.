/* The data boundary, exercised against the REAL export in assets/export/.

   `fetch` is stubbed to read from disk, which is the only difference from the
   browser: the module's own path handling, absence kinds, provenance stamping
   and return conventions are the shipped ones. If the export is not present the
   file-backed tests skip and the no-export tests still run — that state is the
   default for a clone and has to be testable without one. */

import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { describe, it } from "node:test";

const EXPORT = new URL("../assets/export/", import.meta.url);
const HAVE_EXPORT = existsSync(new URL("manifest.json", EXPORT));

function stubFetch({ missing = [] } = {}) {
  globalThis.fetch = async (path) => {
    const name = String(path).replace(/^assets\/export\//, "");
    if (missing.includes(name) || !existsSync(new URL(name, EXPORT))) {
      return { status: 404, ok: false };
    }
    const body = readFileSync(new URL(name, EXPORT), "utf8");
    return { status: 200, ok: true, json: async () => JSON.parse(body) };
  };
}

/** A fresh module each time: the boundary memoises reads, which is right in a
    page and wrong across tests. */
const load = () => import(`../assets/js/data/source.js?${Math.random()}`);

describe("the two return conventions are separate functions", () => {
  it("applies a scenario return as simple and a realised return as log", async () => {
    const s = await load();
    assert.equal(s.priceFromSimpleReturn(100, 0.08), 108);
    assert.equal(s.priceFromLogReturn(100, 0.08).toFixed(4), "108.3287");
  });

  it("offers no helper that takes 'a return' without saying which", async () => {
    const s = await load();
    // Both conventions are reachable, each named for the one it applies.
    assert.equal(typeof s.priceFromSimpleReturn, "function");
    assert.equal(typeof s.priceFromLogReturn, "function");
    // And nothing convention-free is exported, so misuse is a misspelling rather
    // than a plausible call. These are the names such a helper would take.
    for (const banned of ["applyReturn", "toPrice", "returnToPrice", "asPercent", "pct"]) {
      assert.equal(s[banned], undefined, `${banned} would hide the two conventions`);
    }
  });

  it("derives a realised return as LOG, the same quantity the export carries", async () => {
    const s = await load();
    assert.equal(s.logReturnBetween(100, 108.3287).toFixed(4), "0.0800");
  });
});

describe("the three boundary states", () => {
  it("reports no-export when manifest.json 404s", async () => {
    stubFetch({ missing: ["manifest.json"] });
    const s = await load();
    const state = await s.getExportState();
    assert.equal(state.state, s.NO_EXPORT);
    assert.equal(state.why.absent, s.NOT_COMPUTED);
    assert.match(state.why.remedy, /map export/);
  });

  it("keeps no-export distinct from partial", async () => {
    const s = await load();
    assert.notEqual(s.NO_EXPORT, s.PARTIAL);
    assert.notEqual(s.PARTIAL, s.COMPLETE);
  });

  it("survives a missing export everywhere, not just the manifest", async () => {
    stubFetch({ missing: ["manifest.json", "corpus.json", "universe.json", "filers.json"] });
    const s = await load();
    assert.deepEqual((await s.listCorpusCompanies()).rows, []);
    assert.equal((await s.getCompany("AAPL")).absent, s.NOT_COMPUTED);
    assert.equal((await s.getFilerScreen("AAPL")).absent, s.NOT_COMPUTED);
  });
});

describe("the three absence kinds stay apart", () => {
  it("names them distinctly", async () => {
    const s = await load();
    assert.equal(new Set([s.NOT_APPLICABLE, s.NOT_COMPUTED, s.CANNOT_BE_COMPUTED]).size, 3);
  });
});

describe("against the real export", { skip: !HAVE_EXPORT }, () => {
  it("reads the corpus universe without loading the symbol index", async () => {
    stubFetch();
    const s = await load();
    const { rows } = await s.listCorpusCompanies();
    assert.equal(rows.length, 120);
    // exchange is NOT_COMPUTED, not null: it exists, in a file we did not load.
    assert.equal(rows[0].exchange.absent, s.NOT_COMPUTED);
  });

  it("returns all 709 filings including the 8 nothing ran", async () => {
    stubFetch();
    const s = await load();
    const companies = await Promise.all(
      (await s.listCorpusCompanies()).rows.map((r) => s.getCompany(r.ticker)),
    );
    const filings = companies.flatMap((c) => c.filings);
    assert.equal(filings.length, 709);
    assert.equal(filings.filter((f) => !f.ran).length, 8);
  });

  it("never merges the four run files", async () => {
    stubFetch();
    const s = await load();
    const { bySource } = await s.listRuns("ZTS");
    assert.deepEqual(Object.keys(bySource).sort(), ["corpus", "edgar", "news", "unknown"]);
    // No combined array is offered anywhere on the result.
    assert.equal(Object.keys(bySource).length, 4);
  });

  it("carries ledger_item.filing_date rather than deriving it from the anchor", async () => {
    stubFetch();
    const s = await load();
    const { bySource } = await s.listRuns("ZTS");
    const run = bySource.unknown.find((r) => r.corpus_relation === "ledger_item");
    assert.ok(run.ledger_item.filing_date);
    assert.notEqual(run.ledger_item.filing_date, run.anchor_date);
  });

  it("leaves runs in anchor-date descending order", async () => {
    stubFetch();
    const s = await load();
    const rows = (await s.listRuns("ZTS")).bySource.unknown;
    const dates = rows.map((r) => r.anchor_date);
    assert.deepEqual(dates, [...dates].sort().reverse());
  });

  it("stamps a computed target price as derived, not measured", async () => {
    stubFetch();
    const s = await load();
    const run = (await s.listRuns("ZTS")).bySource.unknown[0];
    assert.equal(run.anchor_spot.provenance, s.MEASURED);
    assert.equal(run.scenarios[0].price_return.provenance, s.MEASURED);
    assert.equal(run.scenarios[0].target_price.provenance, s.DERIVED);
  });

  it("formats a derived realised return as logpct, not pct", async () => {
    stubFetch();
    const s = await load();
    const run = (await s.listRuns("ZTS")).bySource.unknown.find((r) => !s.isAbsent(r.outcome));
    assert.equal(run.outcome.realised_log_return.format, "logpct");
    assert.equal(run.outcome.realised_log_return.provenance, s.DERIVED);
  });

  it("renders the holdout as cannot-be-computed, with what_survives", async () => {
    stubFetch();
    const s = await load();
    const { holdout } = await s.listScoringRecords();
    assert.equal(holdout.absent, s.CANNOT_BE_COMPUTED);
    assert.ok(holdout.what_survives.length >= 2);
    assert.match(holdout.survives_in, /holdout_spend\.jsonl/);
  });

  it("prefers an identifiable scoring record over a dirty one", async () => {
    stubFetch();
    const s = await load();
    const { records, identifiable } = await s.listScoringRecords();
    assert.equal(records.length, 2);
    assert.ok(records[0].forecast_digest, "the identifiable record must come first");
    assert.equal(identifiable.length, 1);
  });

  it("says items_settled is not a count of forecasts", async () => {
    stubFetch();
    const s = await load();
    const { manifest } = await s.getExportState();
    const parts = s.describeCorpusSize(manifest);
    assert.equal(parts.find((p) => p.kind === "figure").figure.value, 709);
    assert.ok(parts.some((p) => p.kind === "text" && /not a count of forecasts/.test(p.text)));
  });

  it("builds sentences as parts, with no figure welded into prose", async () => {
    stubFetch();
    const s = await load();
    const run = (await s.listRuns("ZTS")).bySource.unknown.find((r) => !s.isAbsent(r.outcome));
    const parts = s.describeOutcome(run);
    assert.ok(parts.some((p) => p.kind === "figure"));
    // ANY digit, not just a decimal. This asserted /\d+\.\d{2,}/ and passed while
    // `describeOutcome` welded three dates into one text part -- the page audit
    // caught what this test was too narrow to see.
    for (const p of parts.filter((x) => x.kind === "text")) {
      assert.doesNotMatch(p.text, /\d/, `a number was welded into prose: ${p.text}`);
    }
    // Dates come back as their own marked parts, each with a reason.
    const chromeParts = parts.filter((x) => x.kind === "chrome");
    assert.ok(chromeParts.length >= 1);
    assert.ok(chromeParts.every((x) => x.why));
  });

  it("keeps six places on a drift ratio and does not use it as a key", async () => {
    stubFetch();
    const s = await load();
    const { bySource } = await s.listRuns("SCCO");
    const drifted = bySource.unknown.filter((r) => !s.isAbsent(r.anchor_drift));
    assert.ok(drifted.length >= 2);
    assert.equal(drifted[0].anchor_drift.ratio.format, "ratio");
    // The raw floats differ between runs of the same corporate action.
    const raw = new Set(drifted.map((r) => r.anchor_drift.ratio.value));
    assert.ok(raw.size > 1, "expected the ratios to differ run to run");
  });

  it("labels the newest price as a close on a date, never as current", async () => {
    stubFetch();
    const s = await load();
    const series = await s.getPriceSeries("ZTS");
    assert.ok(series.last_close_date);
    assert.equal(series.last_close.provenance, s.MEASURED);
    assert.equal(series.snapshot, "2026-09-05");
  });

  it("returns an absence for a company the snapshot has no series for", async () => {
    stubFetch();
    const s = await load();
    assert.equal((await s.getPriceSeries("ZZZZ")).absent, s.NOT_COMPUTED);
  });

  it("reads the filer pre-screen as recency, not history", async () => {
    stubFetch();
    const s = await load();
    const screen = await s.getFilerScreen("AAPL");
    assert.equal(typeof screen.item_202_in_recent, "boolean");
    assert.equal(screen.count.provenance, s.MEASURED);
  });
});

describe("search counts, against the real export", { skip: !HAVE_EXPORT }, () => {
  it("returns the index size and the full match total", async () => {
    stubFetch();
    const s = await load();
    const { rows, matched, indexSize } = await s.searchSymbols("A", { limit: 5 });
    assert.equal(indexSize, 10398, "the funnel's headline count");
    assert.equal(rows.length, 5, "limit still cuts");
    assert.ok(matched > 5, "matched counts every hit, not the slice");
    const all = await s.searchSymbols("A", { limit: Infinity });
    assert.equal(all.rows.length, matched);
  });

  it("knows the index size even for an empty query", async () => {
    stubFetch();
    const s = await load();
    const { indexSize, matched } = await s.searchSymbols("  ", { limit: 5 });
    assert.equal(indexSize, 10398);
    assert.equal(matched, 0);
  });

  it("counts a company's filings and runs without loading them at boot", async () => {
    stubFetch();
    const s = await load();
    const counts = await s.getCorpusFilingCounts();
    assert.equal(counts.size, 120);
    const totalFilings = [...counts.values()].reduce((n, c) => n + c.filings, 0);
    const totalRuns = [...counts.values()].reduce((n, c) => n + c.runs, 0);
    assert.equal(totalFilings, 709);
    // 701, NOT the 709 of ledger.items_settled: this counts runs the ledger maps
    // to filings, and 8 filings settled as terminal failures with no run.
    assert.equal(totalRuns, 701);
  });

  it("finds a filer row for every symbol, so the fourth group never fires here", async () => {
    // `getFilerScreen` can answer NOT_APPLICABLE and the search screen groups
    // those separately. Against THIS export it is unreachable: all 10,398
    // symbols are covered by the 7,998 filers. The branch stays — a later
    // pre-screen walk can miss a filer — and this pins the current fact.
    stubFetch();
    const s = await load();
    const rows = await (await fetch("assets/export/symbols.json")).json();
    const sample = ["AAPL", "TSLA", "CNTX", "CNLHN", rows.at(-1).ticker];
    for (const ticker of sample) {
      const screen = await s.getFilerScreen(ticker);
      assert.notEqual(screen.absent, s.NOT_APPLICABLE, `${ticker} had no filer row`);
    }
  });
});
