/* Live prices on a company page, in the local app only (ADR 0039).

   What is asserted: the quote says its price, New York's clock, whether the
   market is open, where it came from and that it may be delayed, and is asked
   for again exactly when the server says; the chart covers the window it was
   given, marks what is newer than the snapshot, keeps the record's figures and
   says what it cannot draw; and a copy with no server shows neither. NO EXPORT
   NEEDED. */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";
import { Node, installDom } from "./dom.mjs";

const load = (m) => import(`../assets/js/${m}?${Math.random()}`);
const read = (p) => readFileSync(new URL(`../${p}`, import.meta.url), "utf8");
const walk = function* (n) { yield n; for (const c of n.children ?? []) yield* walk(c); };
const byClass = (root, cls) => [...walk(root)].filter((n) => n._cls?.has(cls) || n.attrs?.class?.split(" ").includes(cls));

/** Timers under the test's hand: what was asked for, and when. */
function clock(start = "2026-09-30T18:32:10Z") {
  let t = new Date(start).getTime();
  const pending = [];
  return {
    now: () => new Date(t),
    wait: (fn, ms) => { const h = { fn, ms }; pending.push(h); return h; },
    cancel: (h) => { const i = pending.indexOf(h); if (i >= 0) pending.splice(i, 1); },
    pending,
    advance(ms) { t += ms; },
  };
}
const settle = () => new Promise((r) => setTimeout(r, 0));

describe("the quote", () => {
  const OPEN = {
    ticker: "KO", at: "2026-09-30T18:31:00+00:00", provider: "yfinance", market: "open",
    new_york: "2026-09-30T14:32-04:00", next_check_s: 60,
  };

  async function mounted(answer, c = clock()) {
    installDom();
    const { figure, MEASURED } = await load("lib/figure.js");
    const { mountQuote } = await load("ui/company-quote.js");
    const host = new Node("section");
    const asked = [];
    const quote = typeof answer === "object" && !answer.absent ? { ...answer, price: figure(70.12, MEASURED, "price") } : answer;
    const handle = mountQuote(host, {
      ticker: "KO", fetchQuote: async (t) => { asked.push(t); return quote; }, now: c.now, wait: c.wait, cancel: c.cancel,
    });
    await settle();
    return { host, asked, handle, c };
  }

  it("says the price, New York's time, that the market is open, and where it came from", async () => {
    const { host } = await mounted(OPEN);
    const text = host.textContent;
    assert.match(text, /^70\.12market open/, "the price first; the title names the company");
    assert.match(text, /New York 14:32/, "the clock in New York now");
    assert.match(text, /Last trade 14:31 New York, from Yahoo Finance via yfinance, and it may be delayed\./);
    assert.match(text, /Asked again about once a minute while the market is open\./);
  });

  it("asks again when the server says, and never sooner than half a minute", async () => {
    const { asked, c } = await mounted(OPEN);
    assert.deepEqual(asked, ["KO"]);
    const next = c.pending.find((h) => h.ms === 60_000);
    assert.ok(next, "about a minute while open");
    const quick = await mounted({ ...OPEN, next_check_s: 5 });
    assert.ok(quick.c.pending.some((h) => h.ms === 30_000), "a floor, whatever a server says");
  });

  it("says the market is closed, when it last traded, and that it waits for the bell", async () => {
    const shut = { ...OPEN, market: "closed", at: "2026-09-29T19:59:00+00:00", next_check_s: 55_800 };
    const { host, c } = await mounted(shut, clock("2026-09-30T00:00:00Z"));
    const text = host.textContent;
    assert.match(text, /market closed/);
    assert.match(text, /Last trade before the close 15:59, Tue 29 Sep New York/);
    assert.match(text, /Asked again at the next opening bell\./);
    assert.ok(c.pending.some((h) => h.ms === 55_800_000));
  });

  it("says why there is no quote, and tries again in a few minutes", async () => {
    const { host, c } = await mounted({ absent: "not-computed", why: "the server did not answer the quote request" });
    assert.match(host.textContent, /No live quote: the server did not answer the quote request\./);
    assert.ok(c.pending.some((h) => h.ms === 300_000));
  });

  it("stops asking when stopped", async () => {
    const { handle, c } = await mounted(OPEN);
    handle.stop();
    assert.equal(c.pending.length, 0);
  });

  it("reads New York's clock in summer and in winter", async () => {
    const { newYork } = await load("ui/company-quote.js");
    assert.equal(newYork(new Date("2026-09-30T18:31:00Z")), "14:31");
    assert.equal(newYork(new Date("2026-12-01T15:00:00Z")), "10:00");
    assert.equal(newYork(new Date("2026-09-29T19:59:00Z"), { day: true }), "15:59, Tue 29 Sep");
  });

  it("is fetched only from a server, and is an absence without one", async () => {
    installDom({ withFetch: false });
    globalThis.fetch = async (path) => {
      if (path === "health") return { ok: true };
      if (String(path).startsWith("quote?ticker=KO")) {
        return { ok: true, json: async () => ({ ...OPEN, price: 70.12 }) };
      }
      return { ok: false, status: 404, json: async () => ({}) };
    };
    const server = await import("../assets/js/data/server.js");
    server.resetProbe();
    const quote = await server.fetchQuote("KO");
    assert.equal(quote.price.value, 70.12);
    assert.equal(quote.price.provenance, "measured");
    assert.equal(quote.market, "open");
    globalThis.fetch = async () => { throw new Error("no server here"); };
    server.resetProbe();
    const none = await server.fetchQuote("KO");
    assert.match(none.why, /no server is behind these files/);
    server.resetProbe();
  });
});

describe("the chart's window", () => {
  const RUN = (anchor, over = {}) => ({
    run_id: `run-${anchor}`, anchor_date: anchor, anchor_spot: 60, outcome_status: "window_open",
    outcome: { absent: "not-applicable", why: "open" }, anchor_drift: { absent: "not-applicable", why: "agrees" },
    ...over,
  });
  const runs = (list) => ({ bySource: { corpus: list, edgar: [], news: [], unknown: [] } });
  const served = (bars, window = { start: "2024-09-30", end: "2026-09-30" }) => ({
    ticker: "KO", served: true, fetched_on: "2026-09-30", provider: "yfinance", adjustment: "split_adjusted",
    window, sessions: bars, last_close: { value: bars.at(-1)[1] }, last_close_date: bars.at(-1)[0],
  });
  const snapshot = (bars) => ({ ticker: "KO", snapshot: "2026-09-05", sessions: bars });
  const BARS = [["2024-09-30", 70], ["2025-06-02", 65], ["2026-09-04", 68], ["2026-09-29", 70.5]];

  async function chart(series, rowList, pinned) {
    installDom();
    const { renderSeries } = await load("ui/company-series.js");
    const { figure, MEASURED } = await load("lib/figure.js");
    const host = new Node("section");
    const measured = { ...series, last_close: figure(series.last_close.value, MEASURED, "price") };
    renderSeries(host, { series: measured, runs: runs(rowList), snapshot: pinned });
    return host;
  }

  it("covers the two years it was given, and says so with the source and its basis", async () => {
    const host = await chart(served(BARS), [], snapshot([["2026-09-04", 68]]));
    const text = host.textContent;
    assert.match(text, /30 Sep 2024 to 30 Sep 2026/);
    assert.match(text, /yfinance, split-adjusted/);
    const dates = byClass(host, "cmp-plot-dates")[0];
    assert.match(dates.textContent, /^2024-09-302026-09-30$/, "the window's ends, not the first and last close");
  });

  it("draws what is newer than the snapshot apart, and labels where it starts", async () => {
    const host = await chart(served(BARS), [], snapshot([["2025-06-02", 65], ["2026-09-04", 68]]));
    assert.equal(byClass(host, "cmp-line--after").length, 2, "the dashed path and its legend swatch");
    assert.match(host.textContent, /newer than the 5 Sep 2026 snapshot →/);
    assert.match(host.textContent, /close, newer than the snapshot/);
  });

  it("puts a run's marks on the line and keeps the record's figure", async () => {
    const host = await chart(served(BARS), [RUN("2025-06-02")], snapshot([["2026-09-04", 68]]));
    assert.equal(byClass(host, "cmp-dot").length, 1);
    assert.equal(byClass(host, "cmp-series-note").length, 0, "nothing to say");
  });

  it("says when a recorded run falls before the window, rather than dropping it", async () => {
    const host = await chart(
      served(BARS),
      [RUN("2024-03-12"), RUN("2024-08-01"), RUN("2025-06-03")],
      snapshot([["2026-09-04", 68]]),
    );
    const notes = byClass(host, "cmp-series-note").map((n) => n.textContent);
    assert.match(notes[0], /2 recorded runs are anchored before 30 Sep 2024, outside this two-year window, so they are not drawn; the earliest is 12 Mar 2024\./);
    assert.match(notes[1], /One run's anchor session is not in this series, so it is not drawn\./);
  });

  it("says when the provider has re-based the series since the snapshot", async () => {
    const host = await chart(served(BARS), [], snapshot([["2026-09-04", 136]]));
    assert.match(host.textContent, /re-based this series by ×0\.5000 — a split or similar/);
    assert.match(host.textContent, /every run's figures are still the record's/);
  });

  it("draws the snapshot as it always did on a copy with no server", async () => {
    const pinned = { ...snapshot(BARS.slice(0, 3)), last_close: { value: 68 }, last_close_date: "2026-09-04" };
    const host = await chart(pinned, [], null);
    assert.equal(byClass(host, "cmp-line--after").length, 0);
    assert.match(host.textContent, /2026-09-05 snapshot/);
    assert.match(byClass(host, "cmp-plot-dates")[0].textContent, /^2024-09-302026-09-04$/);
  });

  it("is wired so: a quote and the window where a server answers, and nothing of either where none does", () => {
    const page = read("assets/js/company.js");
    assert.match(page, /if \(await serverPresent\(\)\) mountQuote\(\$\("quote"\), \{ ticker, fetchQuote \}\);\s*else \$\("quote"\)\?\.remove\(\);/);
    assert.match(page, /renderSeries\(\$\("series"\), \{ series: served, runs: record, snapshot \}\)/);
    assert.match(read("company.html"), /<section id="quote"\s+class="cmp-quote" aria-live="polite"><\/section>/);
  });
});
