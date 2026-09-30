/* One page per company, and live runs kept apart on it — ADR 0036, amendment of
   2026-09-30.

   The separation rule is what these tests are for. A live run is listed in its
   own section, counted in its own fact and never drawn on the record's chart; a
   record count never includes one; and the hosted copy states one absence where
   a run would be offered. */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";
import { itNeedsExport } from "./needs-export.mjs";
import { Node, installDom } from "./dom.mjs";

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");
const load = (path) => import(`../assets/js/${path}?${Math.random()}`);
/* The server module as the page imports it. Its probe is memoised per module
   instance, and `load` makes a fresh instance — so resetting through `load` would
   reset a copy nothing else reads. */
const server = () => import("../assets/js/data/server.js");

/* A live row as the export and the server both write it. */
const RAW = {
  run_id: "b8748710-c5e8-439c-8983-a582d982e609",
  ticker: "KO",
  company_name: null,
  anchor_date: "2026-09-28",
  anchor_spot: 87.33,
  price_kind: "intraday",
  horizon_days: 5,
  scenarios: [
    { name: "bullish", probability_weight: 0.25, price_return: 0.02, annualised_vol: 0.22 },
    { name: "base_case", probability_weight: 0.6, price_return: 0.0, annualised_vol: 0.22 },
    { name: "bearish", probability_weight: 0.15, price_return: -0.01, annualised_vol: 0.22 },
  ],
  document_source: "edgar",
  freeze_version: null,
  arm: null,
  document_is_frozen_exhibit: false,
  corpus_relation: "outside_corpus",
  ledger_item: null,
  anchor_drift: null,
  outcome: null,
  outcome_status: "absent_from_snapshot",
};

describe("the record and the live runs are two sets that never meet", () => {
  it("names the two halves once, and together they are every source", async () => {
    const { SOURCES, RECORD_SOURCES, LIVE_SOURCES } = await load("data/source.js");
    assert.deepEqual([...RECORD_SOURCES, ...LIVE_SOURCES].sort(), [...SOURCES].sort());
    assert.equal(RECORD_SOURCES.filter((s) => LIVE_SOURCES.includes(s)).length, 0);
    assert.deepEqual(LIVE_SOURCES, ["edgar", "news"]);
  });

  it("hands the record's sections the record, and only the live section the rest", () => {
    const page = read("assets/js/company.js");
    const split = page.slice(page.indexOf("function split(runs)"), page.indexOf("async function paint()"));
    assert.match(split, /RECORD_SOURCES\.includes\(name\) \? runs\.bySource\[name\] : \[\]/);
    assert.match(split, /LIVE_SOURCES\.flatMap/);
    const record = page.slice(page.indexOf("async function paintRecord"), page.indexOf("function paintRuns"));
    for (const call of ["renderIdentity", "renderSeries", "renderFilings"]) {
      assert.match(record, new RegExp(`${call}\\(\\$\\("\\w+"\\), \\{[^}]*runs: record`), call);
    }
    assert.match(page, /runs: record,\s*company,\s*open/, "the runs table gets the record");
  });

  it("reads the live list once, for the count and the section alike", () => {
    /* They disagreed in the first build: the count came from the export and the
       section from the server, so KO's page said "2 below" over "No live run". */
    const page = read("assets/js/company.js");
    assert.match(page, /const live = await liveRows\(ticker, exported\)/);
    assert.match(page, /rows: live,/);
    assert.match(page, /onRows: recount/);
  });

  it("repaints only the table when a record row opens, so a streaming run survives", () => {
    const page = read("assets/js/company.js");
    const runs = page.slice(page.indexOf("function paintRuns"), page.indexOf("async function paintFiler"));
    assert.match(runs, /paintRuns\(company, record\)/);
    assert.doesNotMatch(runs, /\bpaint\(\)/);
  });
});

describe("a company outside the corpus has a page", () => {
  it("shows what the export knows about it, and no record facts at all", async () => {
    installDom();
    const { renderFilerIdentity } = await load("ui/company-identity.js");
    const { figure, MEASURED } = await load("lib/figure.js");
    const host = new Node("section");
    renderFilerIdentity(host, {
      filer: {
        ticker: "KO", cik: 21344, exchange: "NYSE",
        screen: { count: figure(40, MEASURED, "int"), most_recent: "2026-07-22", fetched_on: "2026-09-09" },
      },
      liveRuns: 2,
    });
    const text = host.textContent;
    assert.match(text, /Earnings filings, recent block/);
    assert.match(text, /2026-07-22/);
    assert.match(text, /below, outside the record/);
    /* Zeros would read as a record that is empty rather than one that does not
       exist. */
    for (const fact of ["Filings held", "Panel runs", "Runs in the record", "Closed"]) {
      assert.doesNotMatch(text, new RegExp(fact), fact);
    }
  });

  itNeedsExport("is found through the symbol index and the pre-screen", async () => {
    installDom();
    const source = await load("data/source.js");
    const filer = await source.getFiler("KO");
    assert.equal(filer.ticker, "KO");
    assert.ok(!source.isAbsent(filer.screen));
    assert.equal(filer.screen.item_202_in_recent, true);
    assert.ok(source.isAbsent(await source.getCompany("KO")), "and it is not a corpus company");
    const missing = await source.getFiler("ZZZZZ");
    assert.ok(source.isAbsent(missing));
    assert.match(missing.why, /not in the SEC symbol index/);
  });

  it("states the absence of a price series on a copy with no server, with the reason", () => {
    const page = read("assets/js/company.js");
    const filer = page.slice(page.indexOf("async function paintFiler"), page.indexOf("/** The one state the export"));
    assert.match(filer, /\(await serverPresent\(\)\)\s*\?\s*await fetchPrices\(filer\.ticker\)/);
    assert.match(filer, /No price history on this copy/);
    assert.match(filer, /export carries no series for it/);
    // And the record's three sections are removed rather than left empty.
    assert.match(filer, /for \(const id of \["filings", "runs", "scoring"\]\) \$\(id\)\?\.remove\(\)/);
  });

  it("labels a served series with the day it was fetched, not as a snapshot", async () => {
    installDom();
    const { renderSeries } = await load("ui/company-series.js");
    const { figure, MEASURED } = await load("lib/figure.js");
    const host = new Node("section");
    const none = { bySource: { corpus: [], edgar: [], news: [], unknown: [] } };
    renderSeries(host, {
      series: {
        ticker: "KO", served: true, fetched_on: "2026-09-30",
        sessions: [["2026-09-26", 86.9], ["2026-09-29", 87.2]],
        last_close: figure(87.2, MEASURED, "price"), last_close_date: "2026-09-29",
      },
      runs: none,
      title: "Price series",
    });
    assert.match(host.textContent, /fetched 2026-09-30 by this machine/);
    assert.doesNotMatch(host.textContent, /snapshot/);
    assert.match(host.textContent, /^Price series/);
  });
});

describe("search sends a reader to the page, never to a separate screen", () => {
  it("makes a readable filer's row a link to its page, and keeps the others as they were", async () => {
    installDom();
    const { renderResults } = await load("ui/search-box.js");
    const { figure, MEASURED } = await load("lib/figure.js");
    const screen = { count: figure(40, MEASURED, "int"), most_recent: "2026-07-22" };
    const host = new Node("section");
    renderResults(host, {
      phase: "ready",
      query: "k",
      groups: {
        earnings: [{ ticker: "KO", name: "COCA COLA CO", exchange: "NYSE", screen }],
        none: [{ ticker: "KOX", name: "SHELL CO", exchange: "OTC", screen: { count: figure(0, MEASURED, "int") } }],
      },
      matched: 2,
    });
    const rows = [];
    const walk = (n) => { if (n._cls?.has("srch-row")) rows.push(n); n.children?.forEach?.(walk); };
    walk(host);
    const [readable, other] = rows;
    assert.equal(readable.tagName, "A");
    assert.equal(readable.href, "company.html?ticker=KO");
    assert.doesNotMatch(host.textContent, /no page/);
    assert.equal(other.tagName, "DIV");
    assert.match(other.textContent, /nothing to read/);
  });
});

describe("the live section", () => {
  it("on a copy with no server: the list, one absence, and no control", async () => {
    installDom();
    const { resetProbe } = await server();
    resetProbe();
    const { renderLive } = await load("ui/company-live.js");
    const { adaptRunRow } = await load("data/source.js");
    const host = new Node("section");
    await renderLive(host, { ticker: "KO", rows: [adaptRunRow(RAW)], inCorpus: false, replay: null });
    const text = host.textContent;
    assert.match(text, /Live runs, outside the record/);
    assert.match(text, /outside the frozen corpus, so it has no record here/);
    assert.match(text, /No analysis server/);
    assert.match(text, /KO cannot be run from this copy/);
    assert.doesNotMatch(text, /Analyse/, "no control that cannot work");
    assert.match(text, /b8748710/, "the recorded row is listed");
  });

  it("shows the recorded run under the absence, on its own company's page only", async () => {
    installDom();
    const { resetProbe } = await server();
    resetProbe();
    const { renderLive } = await load("ui/company-live.js");
    const replay = { ...RAW, price_taken_at: "2026-09-28T19:52:43+00:00", band: [] };
    const on = new Node("section");
    await renderLive(on, { ticker: "KO", rows: [], inCorpus: false, replay });
    assert.match(on.textContent, /A recorded run, not a live one/);
    assert.match(on.textContent, /Raw fan — uncalibrated/);
    const off = new Node("section");
    await renderLive(off, { ticker: "AAPL", rows: [], inCorpus: true, replay });
    assert.doesNotMatch(off.textContent, /recorded run/);
    assert.match(off.textContent, /No live run for AAPL yet/);
    assert.match(off.textContent, /None of them is part of the record above/);
  });

  it("with a server: the control, the server's own list, and no absence", async () => {
    installDom({ withFetch: false });
    globalThis.fetch = async (path) => {
      if (path === "health") return { ok: true };
      if (String(path).startsWith("runs?ticker=KO")) return { ok: true, json: async () => [RAW] };
      return { ok: false, status: 404, json: async () => ({}) };
    };
    const { resetProbe } = await server();
    resetProbe();
    const { liveRows, renderLive } = await load("ui/company-live.js");
    const host = new Node("section");
    const rows = await liveRows("KO", []);
    assert.equal(rows.length, 1, "the server's journal, not the empty export list");
    await renderLive(host, { ticker: "KO", rows, inCorpus: false, horizon: 10, replay: RAW });
    const text = host.textContent;
    assert.match(text, /Analyse/);
    assert.match(text, /Horizon/);
    assert.match(text, /b8748710/, "listed from the server, not the export");
    assert.doesNotMatch(text, /No analysis server/);
    assert.doesNotMatch(text, /recorded run/, "a machine that can run does not replay");
    resetProbe();
  });
});

describe("the door names the recorded run", () => {
  it("links to its company's live section, reading the company from the export", () => {
    const door = read("assets/js/ui/front-door.js");
    assert.match(door, /a\.href = `company\.html\?ticker=\$\{encodeURIComponent\(replay\.ticker\)\}#live`/);
    assert.match(door, /A recorded live run: /);
    assert.match(read("assets/js/search-page.js"), /replay: await source\.getReplay\(\)/);
  });
});
