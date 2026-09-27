/* The data boundary, exercised against the REAL export in assets/export/.

   `fetch` is stubbed to read from disk, which is the only difference from the
   browser: the module's own path handling, absence kinds, provenance stamping
   and return conventions are the shipped ones. If the export is not present the
   file-backed tests skip and the no-export tests still run — that state is the
   default for a clone and has to be testable without one. */

import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { describe, it } from "node:test";
import { HAVE_EXPORT, itNeedsExport } from "./needs-export.mjs";

const EXPORT = new URL("../assets/export/", import.meta.url);

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

describe("against the real export", () => {
  itNeedsExport("reads the corpus universe without loading the symbol index", async () => {
    stubFetch();
    const s = await load();
    const { rows } = await s.listCorpusCompanies();
    assert.equal(rows.length, 120);
    // exchange is NOT_COMPUTED, not null: it exists, in a file we did not load.
    assert.equal(rows[0].exchange.absent, s.NOT_COMPUTED);
  });

  itNeedsExport("returns all 709 filings including the 8 nothing ran", async () => {
    stubFetch();
    const s = await load();
    const companies = await Promise.all(
      (await s.listCorpusCompanies()).rows.map((r) => s.getCompany(r.ticker)),
    );
    const filings = companies.flatMap((c) => c.filings);
    assert.equal(filings.length, 709);
    assert.equal(filings.filter((f) => !f.ran).length, 8);
  });

  itNeedsExport("never merges the four run files", async () => {
    stubFetch();
    const s = await load();
    const { bySource } = await s.listRuns("ZTS");
    assert.deepEqual(Object.keys(bySource).sort(), ["corpus", "edgar", "news", "unknown"]);
    // No combined array is offered anywhere on the result.
    assert.equal(Object.keys(bySource).length, 4);
  });

  itNeedsExport("carries ledger_item.filing_date rather than deriving it from the anchor", async () => {
    stubFetch();
    const s = await load();
    const { bySource } = await s.listRuns("ZTS");
    const run = bySource.unknown.find((r) => r.corpus_relation === "ledger_item");
    assert.ok(run.ledger_item.filing_date);
    assert.notEqual(run.ledger_item.filing_date, run.anchor_date);
  });

  itNeedsExport("leaves runs in anchor-date descending order", async () => {
    stubFetch();
    const s = await load();
    const rows = (await s.listRuns("ZTS")).bySource.unknown;
    const dates = rows.map((r) => r.anchor_date);
    assert.deepEqual(dates, [...dates].sort().reverse());
  });

  itNeedsExport("stamps a computed target price as derived, not measured", async () => {
    stubFetch();
    const s = await load();
    const run = (await s.listRuns("ZTS")).bySource.unknown[0];
    assert.equal(run.anchor_spot.provenance, s.MEASURED);
    assert.equal(run.scenarios[0].price_return.provenance, s.MEASURED);
    assert.equal(run.scenarios[0].target_price.provenance, s.DERIVED);
  });

  itNeedsExport("formats a derived realised return as logpct, not pct", async () => {
    stubFetch();
    const s = await load();
    const run = (await s.listRuns("ZTS")).bySource.unknown.find((r) => !s.isAbsent(r.outcome));
    assert.equal(run.outcome.realised_log_return.format, "logpct");
    assert.equal(run.outcome.realised_log_return.provenance, s.DERIVED);
  });

  itNeedsExport("renders the holdout as cannot-be-computed, with what_survives", async () => {
    stubFetch();
    const s = await load();
    const { holdout } = await s.listScoringRecords();
    assert.equal(holdout.absent, s.CANNOT_BE_COMPUTED);
    assert.ok(holdout.what_survives.length >= 2);
    assert.match(holdout.survives_in, /holdout_spend\.jsonl/);
  });

  itNeedsExport("prefers an identifiable scoring record over a dirty one", async () => {
    stubFetch();
    const s = await load();
    const { records, identifiable } = await s.listScoringRecords();
    // The rule, not the count: a new scoring pass changes how many records ship.
    const firstDirty = records.findIndex((r) => !r.forecast_digest);
    assert.ok(records.length >= 2, "the export ships a dirty record beside an identified one");
    assert.ok(firstDirty > 0, "an identified record comes first");
    assert.ok(
      records.slice(firstDirty).every((r) => !r.forecast_digest),
      "every identified record sorts before every dirty one",
    );
    assert.deepEqual(identifiable, records.filter((r) => r.forecast_digest));
  });

  itNeedsExport("says items_settled is not a count of forecasts", async () => {
    stubFetch();
    const s = await load();
    const { manifest } = await s.getExportState();
    const parts = s.describeCorpusSize(manifest);
    assert.equal(parts.find((p) => p.kind === "figure").figure.value, 709);
    assert.ok(parts.some((p) => p.kind === "text" && /not a count of forecasts/.test(p.text)));
  });

  itNeedsExport("builds sentences as parts, with no figure welded into prose", async () => {
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

  itNeedsExport("keeps six places on a drift ratio and does not use it as a key", async () => {
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

  itNeedsExport("labels the newest price as a close on a date, never as current", async () => {
    stubFetch();
    const s = await load();
    const series = await s.getPriceSeries("ZTS");
    assert.ok(series.last_close_date);
    assert.equal(series.last_close.provenance, s.MEASURED);
    assert.equal(series.snapshot, "2026-09-05");
  });

  itNeedsExport("returns an absence for a company the snapshot has no series for", async () => {
    stubFetch();
    const s = await load();
    assert.equal((await s.getPriceSeries("ZZZZ")).absent, s.NOT_COMPUTED);
  });

  itNeedsExport("reads the filer pre-screen as recency, not history", async () => {
    stubFetch();
    const s = await load();
    const screen = await s.getFilerScreen("AAPL");
    assert.equal(typeof screen.item_202_in_recent, "boolean");
    assert.equal(screen.count.provenance, s.MEASURED);
  });
});

describe("run counts from the manifest", () => {
  itNeedsExport("returns one read count per runs file and no total", async () => {
    stubFetch();
    const s = await load();
    const { manifest } = await s.getExportState();
    const counts = s.runCountsBySource(manifest);
    assert.deepEqual(Object.keys(counts), s.SOURCES, "four populations, in the files' order, and nothing else");
    for (const source of s.SOURCES) {
      assert.equal(counts[source].provenance, "measured");
      const rows = JSON.parse(readFileSync(new URL(`runs/by_source/${source}.json`, EXPORT), "utf8"));
      assert.equal(counts[source].value, rows.length, `${source} matches its file`);
    }
  });

  itNeedsExport("states an export older than runs.rows as absent, not as zero runs", async () => {
    const s = await load();
    assert.ok(s.isAbsent(s.runCountsBySource({ export_version: "1.1.0" })));
    assert.ok(s.isAbsent(s.runCountsBySource({ runs: { rows: { unknown: 779 } } })), "a partial set is not four counts");
  });
});

describe("search counts, against the real export", () => {
  itNeedsExport("returns the index size and the full match total", async () => {
    stubFetch();
    const s = await load();
    const { rows, matched, indexSize } = await s.searchSymbols("A", { limit: 5 });
    assert.equal(indexSize, 10398, "the funnel's headline count");
    assert.equal(rows.length, 5, "limit still cuts");
    assert.ok(matched > 5, "matched counts every hit, not the slice");
    const all = await s.searchSymbols("A", { limit: Infinity });
    assert.equal(all.rows.length, matched);
  });

  itNeedsExport("counts a term that matches one corpus company as one", async () => {
    /* THE DEFECT THIS PINS. The index holds every listed symbol, including the
       120 the corpus froze, so a corpus company is a hit in BOTH lists. The
       screen added the two totals: AAPL matched one company and reported 2,
       TSLA the same, and TSL matched four and reported 5 — always one too many
       per corpus company.

       Neither the style probe nor the provenance audit can see this. The number
       was marked, derived and correctly rendered; it just disagreed with the
       rows underneath it. Only counting the same thing a second way catches it. */
    stubFetch();
    const s = await load();
    const corpus = (await s.listCorpusCompanies()).rows;

    for (const [term, expected] of [["AAPL", 1], ["TSLA", 1], ["TSL", 4]]) {
      const { rows } = await s.searchSymbols(term, { limit: Infinity });
      const hits = corpus.filter((row) => s.matchesTerm(row, term));
      assert.equal(hits.length, 1, `${term} matches exactly one corpus company`);

      const counted = s.countMatches(rows, hits);
      assert.equal(counted, expected, `${term} reports ${expected}`);
      // And it is never more than the rows a reader can count on the screen.
      assert.equal(counted, new Set([...rows, ...hits].map((r) => r.ticker)).size);
      // The old arithmetic, pinned as wrong so the fix cannot be undone quietly.
      assert.equal(rows.length + hits.length, expected + 1, `${term} summed to one too many`);
    }
  });

  itNeedsExport("counts a corpus company the index does not hold", async () => {
    /* All 120 corpus companies are in this export's index, which is a property
       of the export rather than a guarantee — one frozen before the index was
       last synced would be in the corpus and not the index. Subtracting the
       corpus count from the index count would lose it; a set does not. */
    const s = await load();
    const index = [{ ticker: "AAA", name: "A" }, { ticker: "AAB", name: "B" }];
    const corpusOnly = [{ ticker: "ZZZ", name: "Frozen before the sync" }];
    assert.equal(s.countMatches(index, corpusOnly), 3);
    assert.equal(s.countMatches(index, [{ ticker: "AAA", name: "A" }]), 2, "an overlap counts once");
    assert.equal(s.countMatches([], []), 0);
  });

  itNeedsExport("applies one matching rule to both lists", async () => {
    const s = await load();
    assert.equal(s.matchesTerm({ ticker: "AAPL", name: "Apple Inc." }, "AAP"), true, "ticker prefix");
    assert.equal(s.matchesTerm({ ticker: "MSFT", name: "Apple Inc." }, "APPLE"), true, "name anywhere");
    assert.equal(s.matchesTerm({ ticker: "MSFT", name: "Microsoft" }, "AAPL"), false);
    // A name may be an absence, not a string: universe.json carries null when
    // the symbol index was not exported.
    assert.equal(s.matchesTerm({ ticker: "AAPL", name: s.absent("not-computed", "no index") }, "AAP"), true);
    assert.equal(s.matchesTerm({ ticker: "MSFT", name: s.absent("not-computed", "no index") }, "APPLE"), false);
  });

  itNeedsExport("knows the index size even for an empty query", async () => {
    stubFetch();
    const s = await load();
    const { indexSize, matched } = await s.searchSymbols("  ", { limit: 5 });
    assert.equal(indexSize, 10398);
    assert.equal(matched, 0);
  });

  itNeedsExport("counts a company's filings and runs without loading them at boot", async () => {
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

  itNeedsExport("finds a filer row for every symbol, so the fourth group never fires here", async () => {
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
