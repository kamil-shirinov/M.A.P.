/* When a run was made, beside the price it opened from.

   A run made on 30 September before the New York close opens from the 29th's
   close, and a journal that printed only "2026-09-29" put it on the wrong day.
   What is asserted: the made time is the viewer's own zone, the anchor is the
   session as recorded, a missing time is said and never borrowed, and every row
   carries the two side by side. NO EXPORT NEEDED. */

import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { Node, installDom } from "./dom.mjs";

const load = (m) => import(`../assets/js/${m}?${Math.random()}`);
const NOW = new Date("2026-09-30T20:00:00Z");

describe("the made time", () => {
  it("is the viewer's local time, day and minute", async () => {
    const { madeText } = await load("lib/run-when.js");
    const at = "2026-09-30T18:29:05+00:00";
    assert.equal(madeText(at, { timeZone: "Europe/London", now: NOW }), "30 Sep, 19:29");
    assert.equal(madeText(at, { timeZone: "America/New_York", now: NOW }), "30 Sep, 14:29");
    // Past midnight in the viewer's zone is the next day there.
    assert.equal(madeText("2026-09-30T23:30:00Z", { timeZone: "Asia/Tokyo", now: NOW }), "1 Oct, 08:30");
  });

  it("names the year only when it is not the current one", async () => {
    const { madeText } = await load("lib/run-when.js");
    const later = new Date("2027-02-01T12:00:00Z");
    assert.equal(madeText("2026-09-30T18:29:05Z", { timeZone: "UTC", now: later }), "30 Sep 2026, 18:29");
  });

  it("is nothing at all when the run left no time to read", async () => {
    const { madeText } = await load("lib/run-when.js");
    for (const missing of [null, undefined, "", "not a time", { absent: "cannot-be-computed", why: "no trace" }]) {
      assert.equal(madeText(missing, { timeZone: "UTC", now: NOW }), null, String(missing));
    }
  });
});

describe("the whole clause", () => {
  it("reads as the example: made on the 30th, from the 29th's close", async () => {
    const { runWhen } = await load("lib/run-when.js");
    const run = { made_at: "2026-09-30T18:29:00Z", anchor_date: "2026-09-29", price_kind: "close" };
    assert.equal(runWhen(run, { timeZone: "Europe/London", now: NOW }), "made 30 Sep, 19:29 · from the 29 Sep close");
  });

  it("keeps the anchor exactly as recorded and words it by the kind of price", async () => {
    const { runWhen } = await load("lib/run-when.js");
    const base = { made_at: "2026-09-28T19:52:00Z", anchor_date: "2026-09-28" };
    const at = (kind) => runWhen({ ...base, price_kind: kind }, { timeZone: "America/New_York", now: NOW });
    assert.equal(at("intraday"), "made 28 Sep, 15:52 · from a 28 Sep price taken during that session, not a close");
    assert.equal(at("unknown"), "made 28 Sep, 15:52 · from 28 Sep");
  });

  it("names the anchor's year when it differs from the year the run was made", async () => {
    const { runWhen } = await load("lib/run-when.js");
    const corpus = { made_at: "2026-09-03T04:58:44Z", anchor_date: "2025-03-12", price_kind: "close" };
    assert.equal(runWhen(corpus, { timeZone: "UTC", now: NOW }), "made 3 Sep, 04:58 · from the 12 Mar 2025 close");
  });

  it("says so when the time was not recorded, rather than borrowing one", async () => {
    const { runWhen } = await load("lib/run-when.js");
    const run = { made_at: { absent: "cannot-be-computed", why: "no trace" }, anchor_date: "2026-09-29", price_kind: "close" };
    assert.equal(runWhen(run, { timeZone: "UTC", now: NOW }), "from the 29 Sep close · when it was made was not recorded");
  });
});

describe("the journal row", () => {
  const raw = (over = {}) => ({
    run_id: "7f234c71-85f1-41f2-8cef-613f04928578",
    ticker: "KO",
    company_name: "Coca-Cola",
    anchor_date: "2026-09-29",
    made_at: "2026-09-30T12:21:11+00:00",
    anchor_spot: 70.12,
    price_kind: "close",
    horizon_days: 5,
    scenarios: ["bullish", "base_case", "bearish"].map((name) => ({
      name, probability_weight: 1 / 3, price_return: 0.01, annualised_vol: 0.2,
    })),
    document_source: "edgar",
    freeze_version: "2.5.0",
    arm: null,
    document_is_frozen_exhibit: false,
    corpus_relation: "outside_corpus",
    ledger_item: null,
    anchor_drift: null,
    outcome: null,
    outcome_status: "window_open",
    ...over,
  });

  async function rendered(run) {
    installDom();
    const { adaptRunRow } = await load("data/source.js");
    const { COLUMNS, renderRowsInto } = await load("ui/runs-journal.js");
    const host = new Node("div");
    renderRowsInto(host, {
      rows: [adaptRunRow(run)],
      ctx: { universe: new Map(), openRows: new Set(), onToggleRow() {} },
      columns: COLUMNS,
    });
    return { COLUMNS, host };
  }

  const find = (node, cls) => {
    if (node.className?.split?.(" ").includes(cls)) return node;
    for (const c of node.children ?? []) {
      const hit = find(c, cls);
      if (hit) return hit;
    }
    return null;
  };

  it("puts the made time right beside the anchor", async () => {
    const { COLUMNS, host } = await rendered(raw());
    const labels = COLUMNS.map(([label]) => label);
    assert.equal(labels.indexOf("Made"), labels.indexOf("Anchored") + 1);
    assert.equal(find(host, "runs-c-date").textContent, "2026-09-29", "the anchor is untouched");
    assert.match(find(host, "runs-c-made").textContent, /^30 Sep, \d\d:21$/);
  });

  it("shows a dash, not a borrowed time, for a run with no trace", async () => {
    const { host } = await rendered(raw({ made_at: null }));
    assert.equal(find(host, "runs-c-made").textContent, "—");
  });
});
