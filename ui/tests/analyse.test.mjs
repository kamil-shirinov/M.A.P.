/* Live analysis, on the company page — ADR 0036 §1 and §4, and its amendment
   of 2026-09-30 that retired the separate screen.

   The load-bearing property is that a fan cannot reach the screen without its
   marking. That is asserted as a refusal rather than as a rendering detail: if a
   later change drops the marking, `renderFan` throws instead of drawing a fan
   that looks settled. */

import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { describe, it } from "node:test";
import { itNeedsExport } from "./needs-export.mjs";
import { Node, installDom } from "./dom.mjs";

/* A local DOM stub, as company, runs, results and front-door each keep one.
   Four copies is a smell, but a fifth convention would be worse than a fifth
   copy: these tests are the thing that has to stay readable. */


const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");

/** Every node under `root`, depth first, in document order. */
const descendants = (root) => {
  const out = [];
  const walk = (n) => { out.push(n); (n.children ?? []).forEach(walk); };
  (root.children ?? []).forEach(walk);
  return out;
};
const load = (path) => import(`../assets/js/${path}?${Math.random()}`);

const RESULT = {
  event: "result",
  run_id: "r-1",
  ticker: "AAPL",
  anchor: "2026-09-22",
  spot: 200,
  horizon_days: 5,
  filed: "2026-09-21",
  accession: "0000320193-26-000077",
  scenarios: [
    { name: "bullish", weight: 0.25, price_return: 0.06, annualised_vol: 0.34 },
    { name: "base_case", weight: 0.5, price_return: 0.01, annualised_vol: 0.28 },
    { name: "bearish", weight: 0.25, price_return: -0.05, annualised_vol: 0.41 },
  ],
  marking: "settled",
  corrected: true,
  reasons: [],
  correction: { a: -0.0757, b: 1.3305, form: "z -> (z - a) / b" },
};

const amber = () => ({
  ...RESULT,
  marking: "uncalibrated",
  corrected: false,
  reasons: ["horizon is 21 sessions; the correction was fitted at 5 and at no other"],
});

describe("a fan cannot be drawn without its marking", () => {
  it("refuses a result that carries none", async () => {
    installDom();
    const { renderFan } = await load("ui/analyse-fan.js");
    const host = new Node("div");
    const { marking, ...unmarked } = RESULT;
    assert.throws(() => renderFan(host, unmarked), /without its marking/);
    assert.throws(() => renderFan(host, null), /without its marking/);
    assert.equal(host.children.length, 0, "nothing was drawn");
  });

  it("puts the marking on the figure itself, so a screenshot carries it", async () => {
    installDom();
    const { renderFan } = await load("ui/analyse-fan.js");
    const settled = renderFan(new Node("div"), RESULT);
    assert.equal(settled.dataset.calibration, "settled");
    const raw = renderFan(new Node("div"), amber());
    assert.equal(raw.dataset.calibration, "uncalibrated");
  });
});

describe("the scenarios are read the way the export states them", () => {
  it("treats price_return as a SIMPLE return, not a log one", async () => {
    /* `format.js` keeps two helpers apart for this: `spot * exp(r)` is invisible
       below about 4% and then diverges one-directionally, which looks like a
       plausible price at every magnitude. At +6% on a spot of 200 the two give
       212.00 and 212.37. */
    installDom();
    const { renderFan } = await load("ui/analyse-fan.js");
    const host = new Node("div");
    renderFan(host, RESULT);
    const text = host.textContent;
    assert.match(text, /212\.00/, "simple return: 200 * (1 + 0.06)");
    assert.doesNotMatch(text, /212\.37/, "log return would give this");
  });

  it("reports every scenario with its weight", async () => {
    installDom();
    const { renderFan } = await load("ui/analyse-fan.js");
    const host = new Node("div");
    renderFan(host, RESULT);
    for (const label of ["Bullish", "Base case", "Bearish"]) {
      assert.ok(host.textContent.includes(label), label);
    }
    assert.match(host.textContent, /50%/, "the base case's weight");
  });
});

describe("the marking says which state it is and why", () => {
  it("names the three conditions when the correction was applied", async () => {
    installDom();
    const { renderMarking } = await load("ui/analyse-fan.js");
    const host = new Node("div");
    renderMarking(host, RESULT);
    assert.match(host.textContent, /Corrected fan/);
    assert.match(host.textContent, /five sessions/);
    assert.match(host.textContent, /within one trading day/);
  });

  it("still refuses the word calibrated on a corrected fan", async () => {
    /* ADR 0036's consequence: the company is outside the frozen corpus, so the
       three conditions make applying the correction defensible, not verified. */
    installDom();
    const { renderMarking } = await load("ui/analyse-fan.js");
    const host = new Node("div");
    renderMarking(host, RESULT);
    assert.match(host.textContent, /not a calibrated fan/i);
    assert.match(host.textContent, /defensible, not verified/);
  });

  it("prints every failing reason rather than summarising them", async () => {
    installDom();
    const { renderMarking } = await load("ui/analyse-fan.js");
    const host = new Node("div");
    const result = amber();
    result.reasons = ["horizon is 21 sessions", "the corpus filters would reject this company: illiquid"];
    renderMarking(host, result);
    for (const reason of result.reasons) assert.ok(host.textContent.includes(reason), reason);
  });

  it("says a raw fan is the one measured too narrow", async () => {
    installDom();
    const { renderMarking } = await load("ui/analyse-fan.js");
    const host = new Node("div");
    renderMarking(host, amber());
    assert.match(host.textContent, /measured too narrow/);
  });
});

describe("the band is the width the forecast claims", () => {
  const banded = (over = {}) => ({
    ...RESULT,
    band: [
      { level: 0.1, price: 188 },
      { level: 0.25, price: 195 },
      { level: 0.75, price: 209 },
      { level: 0.9, price: 216 },
    ],
    ...over,
  });

  it("draws the band behind the scenario lines", async () => {
    installDom();
    const { renderFan } = await load("ui/analyse-fan.js");
    const host = new Node("div");
    const svg = renderFan(host, banded());
    const all = descendants(svg);
    const bands = all.filter((n) => n._cls?.has("anl-band"));
    const paths = all.filter((n) => n._cls?.has("anl-path"));
    assert.equal(bands.length, 2, "two nested ribbons from a four-level band");
    assert.ok(all.indexOf(bands.at(-1)) < all.indexOf(paths[0]), "behind the lines");
  });

  it("takes the axis from the band too, so the ribbon is not clipped", async () => {
    /* The band is usually wider than the three scenarios. An axis fitted to the
       scenarios alone cuts it at the frame and it reads as narrower than it is. */
    installDom();
    const { renderFan } = await load("ui/analyse-fan.js");
    const host = new Node("div");
    const svg = renderFan(host, banded());
    const ticks = descendants(svg).filter((n) => n._cls?.has("anl-ytick"));
    const levels = ticks.map((t) => Number(t.textContent));
    assert.ok(Math.min(...levels) <= 190, "the axis reaches the band's floor");
    assert.ok(Math.max(...levels) >= 210, "and its ceiling");
  });

  it("carries the marking onto the band, so a raw band is amber too", async () => {
    const sheet = read("assets/styles/analyse.css");
    assert.match(sheet, /\.anl-fan\[data-calibration="uncalibrated"\] \.anl-band/);
  });

  it("renders no band rather than inventing one", async () => {
    installDom();
    const { renderFan } = await load("ui/analyse-fan.js");
    const svg = renderFan(new Node("div"), { ...RESULT, band: [] });
    assert.equal(svg.children.filter((n) => n._cls?.has("anl-band")).length, 0);
  });
});

describe("a live result says how it relates to the corpus", () => {
  it("uses the journal's own words, not a second vocabulary", async () => {
    const { RELATIONS } = await import("../assets/js/ui/runs-filters.js");
    const labels = Object.fromEntries(RELATIONS);
    assert.equal(labels.repeat_of_exhibit, "repeat");
    assert.equal(labels.outside_corpus, "outside corpus");
    assert.match(read("assets/js/ui/live-result.js"), /RELATIONS\.find\(\(\[v\]\) => v === event\.corpus_relation\)/);
  });

  it("never claims the latest filing is new", () => {
    /* It is not, for most corpus companies: AAPL's most recent Item 2.02 is the
       one already in its table, and stays so until Q3 arrives. */
    /* Comments out first: the module explains in prose WHY the old claim was
       removed, and that explanation quotes it. */
    const live = read("assets/js/ui/company-live.js").replace(/\/\*[\s\S]*?\*\//g, "");
    assert.doesNotMatch(live, /is not one of the filings above/);
    // Joined first: the sentence is split across concatenated string literals.
    const prose = live.replace(/" \+\s*"/g, "");
    assert.match(prose, /may be one of those above or a newer one/);
    assert.match(prose, /the result says which/);
  });
});

describe("the page, its markup and its rules", () => {
  it("marks the uncalibrated horizons on the control, before anything runs", () => {
    /* A reader choosing 21 sessions should know it is uncalibrated while
       choosing it, not discover it from a result seven minutes later. In the
       shared module, so every screen that offers a run marks them identically. */
    const offer = read("assets/js/ui/analyse-offer.js");
    assert.match(offer, /days: 10, label: "10 sessions", note: "uncalibrated"/);
    assert.match(offer, /days: 21, label: "21 sessions", note: "uncalibrated"/);
    assert.match(offer, /days: 5, label: "5 sessions", note: "the fitted horizon"/);
    assert.match(offer, /note\.dataset\.calibration = "uncalibrated"/);
  });

  it("states one absence rather than disabling a control per row", () => {
    const offer = read("assets/js/ui/analyse-offer.js");
    assert.match(offer, /No analysis server/);
    assert.match(offer, /nothing is pending/);
    // Nowhere, on any screen that can offer a run — not even while one streams:
    // the control is marked busy and a second press does nothing.
    for (const file of ["company.js", "search-page.js", "ui/analyse-offer.js", "ui/search-box.js", "ui/company-live.js"]) {
      assert.doesNotMatch(read(`assets/js/${file}`), /\.disabled = true/, file);
    }
    assert.match(read("assets/js/ui/company-live.js"), /setAttribute\("aria-busy", "true"\)/);
  });

  it("gives every screen the same absence, in the same words", () => {
    /* One module, so a screen that offers a run cannot drift into its own
       explanation of the same missing thing. Only the company page offers one
       now, and search — which no longer does — states no absence at all. */
    const offer = read("assets/js/ui/analyse-offer.js");
    assert.equal((offer.match(/No analysis server/g) ?? []).length, 1);
    const live = read("assets/js/ui/company-live.js");
    assert.match(live, /renderNoServer\(/);
    assert.doesNotMatch(live, /No analysis server/);
    assert.doesNotMatch(read("assets/js/search-page.js"), /renderNoServer|noServerNotes|serverPresent/);
  });

  it("states the absence in one line and puts the reasoning in the notes", () => {
    /* It was four paragraphs on screen. The reasoning is worth having; a reader
       should meet it when they go looking, not on the way past. */
    const offer = read("assets/js/ui/analyse-offer.js");
    const box = offer.slice(offer.indexOf("export function renderNoServer"), offer.indexOf("export function noServerNotes"));
    assert.equal((box.match(/el\("p"/g) ?? []).length, 1, "one paragraph in the box");
    assert.doesNotMatch(box, /el\("pre"/, "the command belongs in the notes");
    assert.match(box, /runs on the machine that has the models/);
    assert.match(box, /static record/);

    const notes = offer.slice(offer.indexOf("export function noServerNotes"));
    assert.match(notes, /uv run map serve/);
    assert.match(notes, /Nothing is queued and nothing is pending/);
    assert.match(notes, /six to twelve minutes/);
  });

  it("adds those notes only on a screen that has no button", () => {
    const page = read("assets/js/company.js");
    assert.match(page, /noServerNotes\(\)/);
    assert.match(page, /\? \[\] : \[noServerNotes\(\)\]/, "added conditionally");
  });

  it("asks whether a server is there without being able to start a run", () => {
    // `health` with GET. A speculative POST would cost seven minutes to find out.
    const server = read("assets/js/data/server.js");
    const body = server.slice(server.indexOf("export function serverPresent()"));
    assert.match(body.slice(0, 300), /fetch\("health", \{ method: "GET" \}\)/);
  });

  it("probes once per page, not once per row", () => {
    /* One answer per page, from one module. The offer module re-exports it
       rather than keeping a second memo that could disagree. */
    const server = read("assets/js/data/server.js");
    assert.match(server, /probe \?\?= fetch/);
    assert.match(read("assets/js/ui/analyse-offer.js"), /export \{ resetProbe, serverPresent \} from "\.\.\/data\/server\.js"/);
    assert.doesNotMatch(read("assets/js/ui/analyse-offer.js"), /probe \?\?=/);
    assert.doesNotMatch(read("assets/js/ui/search-box.js"), /serverPresent/);
  });

  it("sends a search row to the company's page rather than posting from it", () => {
    /* The run belongs to the page of the company it is about, where its progress
       and result have somewhere to go. A readable filer's row is a link there. */
    const box = read("assets/js/ui/search-box.js");
    assert.match(box, /node\.href = `company\.html\?ticker=/);
    assert.doesNotMatch(box, /analyse\.html|method: "POST"|no page/);
    // The one POST in the app, in the one module that talks to the server.
    for (const file of ["ui/analyse-offer.js", "ui/company-live.js", "company.js", "search-page.js"]) {
      assert.doesNotMatch(read(`assets/js/${file}`), /method: "POST"/, file);
    }
    assert.match(read("assets/js/data/server.js"), /fetch\("analyse", \{\s*method: "POST"/);
  });

  it("carries an old link's horizon to the control without starting a run", () => {
    /* A link that spent minutes and wrote a permanent journal entry on arrival
       would make the back button expensive. The horizon preselects; only the
       button runs. */
    const page = read("assets/js/company.js");
    assert.match(page, /params\.get\("horizon"\)/);
    const live = read("assets/js/ui/company-live.js");
    const render = live.slice(live.indexOf("export async function renderLive"), live.indexOf("function paintRows"));
    assert.match(render, /onRun: \(days\) => run\(/, "run() only behind the button");
    assert.doesNotMatch(render.replace(/onRun: \(days\) => run\(/, ""), /\brun\(/);
  });

  it("reads the stream as it arrives rather than buffering it", () => {
    /* Buffering would turn a six-minute progress display into a six-minute
       blank, which is the whole reason the response is newline-delimited. */
    const server = read("assets/js/data/server.js");
    assert.match(server, /getReader\(\)/);
    assert.match(server, /TextDecoder/);
    assert.doesNotMatch(server, /await response\.text\(\)/);
  });

  it("puts the live section last on the company page, after the record", () => {
    const html = read("company.html");
    const order = ["identity", "series", "filings", "runs", "scoring", "live", "why"]
      .map((id) => html.indexOf(`id="${id}"`));
    assert.ok(order.every((i) => i > 0), "every section has a host");
    assert.deepEqual(order, [...order].sort((a, b) => a - b), "in page order, live after the record");
    assert.match(html, /analyse\.css/);
  });

  it("redirects the retired screen's links to the company page", () => {
    /* Old links keep working. A ticker and a horizon go to that company's live
       section; no ticker goes to the recorded run's company, read from the
       manifest rather than hardcoded; failing that, to search. */
    const html = read("analyse.html");
    assert.doesNotMatch(html, /type="module"/, "no app script: it only moves the reader on");
    assert.match(html, /company\.html\?ticker=/);
    assert.match(html, /#live/);
    assert.match(html, /m\.replay && m\.replay\.exported_as/);
    assert.match(html, /location\.replace\("index\.html"\)/);
    assert.doesNotMatch(html, /\bKO\b/, "the recorded company is read, not written in");
  });

  it("keeps amber to the one meaning, in this stylesheet too", () => {
    // The same discipline the company screen pins, applied to the new sheet.
    const sheet = read("assets/styles/analyse.css").replace(/\/\*[\s\S]*?\*\//g, "");
    const amberRules = sheet
      .split("}")
      .filter((block) => /var\(--uncal/.test(block))
      .map((block) => block.split("{")[0].trim());
    assert.ok(amberRules.length >= 3, "the sheet does use amber");
    for (const selector of amberRules) {
      assert.match(selector, /data-calibration="uncalibrated"/, selector);
    }
  });

  it("gives every screen a nav host, except the redirect that has no screen", () => {
    for (const page of readdirSync(new URL("../", import.meta.url)).filter((f) => f.endsWith(".html"))) {
      if (page === "analyse.html") continue;
      assert.match(read(page), /<div id="masthead-nav"><\/div>/, page);
    }
  });
});

describe("a shared component's rules reach every page that renders it", () => {
  /* The defect this exists for: `analyse-offer.js` was rendered from the search
     and company pages while `analyse.css` was linked only from analyse.html, so
     the absence block appeared unstyled — no border, no background, no measure.
     Nothing in the markup was wrong and no test could see it. */
  const OFFER_CLASSES = ["anl-absent", "anl-periods", "anl-period-note"];
  const PAGES = { "index.html": "search-page.js", "company.html": "company.js" };

  it("links analyse.css from every page that can render the offer", () => {
    for (const page of Object.keys(PAGES)) {
      assert.match(read(page), /assets\/styles\/analyse\.css/, page);
    }
  });

  it("defines every class the shared module emits", () => {
    const sheet = read("assets/styles/analyse.css");
    const emitted = read("assets/js/ui/analyse-offer.js");
    for (const cls of OFFER_CLASSES) {
      assert.ok(emitted.includes(cls), `the module emits .${cls}`);
      assert.ok(sheet.includes(`.${cls}`), `analyse.css defines .${cls}`);
    }
  });

  it("loads analyse.css before system.css, as the other sheets are ordered", () => {
    // system.css carries the page-level overrides and has to win.
    for (const page of Object.keys(PAGES)) {
      const html = read(page);
      assert.ok(
        html.indexOf("styles/analyse.css") < html.indexOf("styles/system.css"),
        `${page} loads analyse.css before system.css`,
      );
    }
  });
});

describe("the door counts live runs, which is not the same set as outside_corpus", () => {
  const EXPORT = new URL("../assets/export/", import.meta.url);
  const exported = (name) => JSON.parse(readFileSync(new URL(name, EXPORT), "utf8"));

  it("says live runs rather than naming a larger set", () => {
    /* The clause can only see what the manifest counts per document source.
       `corpus_relation` calls more runs `outside_corpus` than that — runs made
       before the source field existed carry `unknown` and can still be outside
       the corpus — so labelling this count "outside the corpus" would put a
       number on the door that the runs screen contradicts. */
    const door = read("assets/js/ui/front-door.js");
    assert.match(door, /" live run" : " live runs"/);
    assert.doesNotMatch(door, /chromeText\(\s*" outside the corpus"/);
  });

  itNeedsExport("and the two really do differ in this export", () => {
    const rows = ["corpus", "edgar", "news", "unknown"]
      .flatMap((s) => exported(`runs/by_source/${s}.json`).map((e) => [s, e.corpus_relation]));
    const live = rows.filter(([s]) => s === "edgar" || s === "news").length;
    const outside = rows.filter(([, r]) => r === "outside_corpus").length;
    // If these ever coincide the distinction still holds; it is just not visible
    // here, and this assertion says which case the export is in.
    assert.ok(outside >= live, "outside_corpus is the larger set");
    assert.notEqual(outside, live, "and in this export they differ, which is why the label matters");
  });

  it("keeps the one-line finding on the door", () => {
    // The door's only claim about results. It sits last and must not be crowded
    // out by a count that arrived later.
    const door = read("assets/js/ui/front-door.js");
    assert.match(door, /does not beat a plain random walk or GARCH/);
  });
});

describe("one status, one label", () => {
  it("names an absent outcome by its own status, not always window open", async () => {
    /* Every absent outcome used to read "window open" — one of four reasons the
       filter offers. KO's horizon is not open: its anchor is past the end of a
       snapshot pinned three weeks earlier. */
    const journal = read("assets/js/ui/runs-journal.js");
    assert.match(journal, /outcomeLabel\(run\)/);
    assert.doesNotMatch(
      journal.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, ""),
      /"runs-c-open", "window open"/,
    );
  });

  it("takes the words from the filter's own table", async () => {
    const { OUTCOMES } = await import("../assets/js/ui/runs-filters.js");
    const labels = Object.fromEntries(OUTCOMES);
    assert.equal(labels.absent_from_snapshot, "absent from snapshot");
    assert.equal(labels.window_open, "window open");
    assert.match(read("assets/js/ui/runs-journal.js"), /OUTCOMES\.find\(\(\[v\]\) => v === status\)/);
  });

  it("gives each status its own reason rather than one for all of them", () => {
    const journal = read("assets/js/ui/runs-journal.js");
    for (const status of ["window_open", "absent_from_snapshot", "not_requested"]) {
      assert.match(journal, new RegExp(`${status}:`), status);
    }
  });

  itNeedsExport("and the live run in this export is absent_from_snapshot", () => {
    const rows = JSON.parse(readFileSync(new URL("../assets/export/runs/by_source/edgar.json", import.meta.url), "utf8"));
    if (!rows.length) return;
    assert.equal(rows[0].outcome_status, "absent_from_snapshot");
    assert.equal(rows[0].outcome, null);
  });
});

describe("the shaded region is named", () => {
  const banded = {
    ...RESULT,
    band: [
      { level: 0.1, price: 188 }, { level: 0.25, price: 195 },
      { level: 0.75, price: 209 }, { level: 0.9, price: 216 },
    ],
  };

  it("says what the shading is, and whether it was widened", async () => {
    /* Shading with no legend is a region a reader has to guess at, and the guess
       available is "the scenarios" — which it is not. */
    installDom();
    const { renderFan } = await load("ui/analyse-fan.js");
    const host = new Node("div");
    renderFan(host, banded);
    assert.match(host.textContent, /middle 80% and 50% of the forecast\./);
    assert.match(host.textContent, /The fitted correction widened this\./);
  });

  it("says the raw band is the width measured too narrow", async () => {
    installDom();
    const { renderFan } = await load("ui/analyse-fan.js");
    const host = new Node("div");
    renderFan(host, { ...banded, corrected: false, marking: "uncalibrated" });
    assert.match(host.textContent, /This raw width was measured too narrow\./);
  });

  it("adds no legend when there is no band", async () => {
    installDom();
    const { renderFan } = await load("ui/analyse-fan.js");
    const host = new Node("div");
    renderFan(host, { ...RESULT, band: [] });
    assert.doesNotMatch(host.textContent, /Shaded:/);
  });
});

describe("the hosted copy replays one recorded run", () => {
  itNeedsExport("pins it by run id in the manifest, never the newest", () => {
    /* "The newest live run" would republish whatever happened locally, which is a
       live claim by another route — and it would have published the accidental
       run of Findings #63. */
    const manifest = JSON.parse(readFileSync(new URL("../assets/export/manifest.json", import.meta.url), "utf8"));
    assert.equal(manifest.replay.run_id, "b8748710-c5e8-439c-8983-a582d982e609");
    assert.equal(manifest.replay.exported_as, "live/replay.json");
  });

  itNeedsExport("exports the run as the journal recorded it", () => {
    const row = JSON.parse(readFileSync(new URL("../assets/export/live/replay.json", import.meta.url), "utf8"));
    assert.equal(row.run_id, "b8748710-c5e8-439c-8983-a582d982e609");
    assert.equal(row.document_source, "edgar");
    assert.equal(row.corpus_relation, "outside_corpus");
    assert.equal(row.scenarios.length, 3);
  });

  it("labels it as recorded and offers no theatre", () => {
    /* No replayed progress stream, no elapsed counter. Making a record look like
       an event is the one thing this page must not do. */
    const result = read("assets/js/ui/live-result.js");
    const fn = result.slice(result.indexOf("export function recordedNote"));
    assert.match(fn, /A recorded run, not a live one/);
    assert.match(fn, /Nothing here was computed just now/);
    assert.doesNotMatch(fn, /setInterval|setTimeout|requestAnimationFrame/);
  });

  it("shows it only when there is no server, and only on its own company's page", () => {
    const live = read("assets/js/ui/company-live.js");
    const render = live.slice(live.indexOf("export async function renderLive"), live.indexOf("function paintRows"));
    const served = render.slice(render.indexOf("if (live) {"), render.indexOf("return box;") );
    assert.doesNotMatch(served, /replay/);
    const hosted = render.slice(render.indexOf("return box;"));
    assert.match(hosted, /replay\.ticker === ticker/);
    assert.match(hosted, /recordedNote\(replay\)/);
  });

  it("marks the replayed fan uncalibrated, like any other raw one", () => {
    const result = read("assets/js/ui/live-result.js");
    const fn = result.slice(result.indexOf("export function replayAsResult"), result.indexOf("export function recordedNote"));
    assert.match(fn, /marking: "uncalibrated"/);
    assert.match(fn, /corrected: false/);
  });

  it("draws the exported band rather than sampling a second one", () => {
    /* The page used to sample its own in JavaScript. Two estimators of one
       quantity is the quickest way to have two answers and no way to say which
       is the one a score would be computed against — they agreed to 0.6% here,
       which is a property of large samples and not a guarantee. */
    const result = read("assets/js/ui/live-result.js");
    assert.doesNotMatch(result, /bandFrom/);
    assert.doesNotMatch(result, /xorshift/);
    assert.match(result, /band: row\.band \?\? \[\]/);
  });

  itNeedsExport("and that band came from simulate(), with the run's own scenarios", () => {
    const row = JSON.parse(readFileSync(new URL("../assets/export/live/replay.json", import.meta.url), "utf8"));
    assert.equal(row.band.length, 4);
    assert.deepEqual(row.band.map((b) => b.level), [0.1, 0.25, 0.75, 0.9]);
    const prices = row.band.map((b) => b.price);
    assert.deepEqual(prices, [...prices].sort((a, b) => a - b));
    // Wider than the three scenarios, which is the reason it is drawn.
    const ends = row.scenarios.map((s) => row.anchor_spot * (1 + s.price_return));
    assert.ok(prices[0] < Math.min(...ends) && prices[3] > Math.max(...ends));
  });

  itNeedsExport("says the pinned run's price was intraday, not a close", () => {
    /* It was taken at 15:52 in New York, eight minutes before the bell. Saying
       "at that day's close" on a public page would be false about a real
       company's price. */
    const row = JSON.parse(readFileSync(new URL("../assets/export/live/replay.json", import.meta.url), "utf8"));
    assert.equal(row.price_kind, "intraday");
    assert.match(row.price_taken_at, /^2026-09-28T19:52/);
    assert.match(read("assets/js/ui/live-result.js"), /price taken during that session/);
  });
});

describe("each drifted run is labelled by its own cause", () => {
  const rows = () => ["unknown", "edgar"].flatMap((s) =>
    JSON.parse(readFileSync(new URL(`../assets/export/runs/by_source/${s}.json`, import.meta.url), "utf8")));

  itNeedsExport("AAPL's two were priced before the close, SCCO's seven re-based", () => {
    /* Every screen called all nine "re-based by a corporate action". AAPL's were
       made at 13:02 and 13:11 New York time on a session still trading. */
    const drifted = rows().filter((r) => r.anchor_drift);
    const byTicker = (t) => drifted.filter((r) => r.ticker === t).map((r) => r.anchor_drift.cause);
    assert.deepEqual([...new Set(byTicker("AAPL"))], ["intraday_anchor"]);
    assert.equal(byTicker("AAPL").length, 2);
    assert.deepEqual([...new Set(byTicker("SCCO"))], ["corporate_action"]);
    assert.equal(byTicker("SCCO").length, 7);
  });

  it("takes every screen's words from one table", async () => {
    const { DRIFT_CAUSES } = await import("../assets/js/data/source.js");
    assert.equal(DRIFT_CAUSES.corporate_action.short, "re-based");
    assert.equal(DRIFT_CAUSES.intraday_anchor.short, "priced before the close");
    for (const file of ["ui/runs-journal.js", "ui/company-series.js"]) {
      assert.match(read(`assets/js/${file}`), /DRIFT_CAUSES/, file);
    }
    // The drift panel no longer names one cause for all of them.
    const header = read("assets/js/ui/runs-header.js");
    assert.doesNotMatch(header, /card\(root, "Re-based since the run"\)/);
    assert.match(header, /drift\.cause === "intraday_anchor"/);
  });
});

describe("the fan, session by session", () => {
  /* A result as the server sends it: nineteen levels at every session from the
     anchor to the horizon, each scenario's curve, and the closes before it. */
  const LEVELS = Array.from({ length: 19 }, (_, k) => Math.round((k + 1) * 5) / 100);
  const fanned = (over = {}) => {
    const sessions = [0, 1, 2, 3, 4, 5].map((t) => ({
      session: t,
      prices: LEVELS.map((q) => 200 * (1 + (q - 0.5) * 0.04 * Math.sqrt(t))),
    }));
    return {
      ...RESULT,
      band: [],
      fan: { levels: LEVELS, sessions },
      scenario_paths: RESULT.scenarios.map((s) => ({
        name: s.name, weight: s.weight,
        prices: [0, 1, 2, 3, 4, 5].map((t) => 200 * (1 + s.price_return) ** (t / 5)),
      })),
      history: [["2026-07-01", 190], ["2026-08-03", 196], ["2026-09-22", 200]],
      ...over,
    };
  };

  it("grades in nine central intervals, outermost first, from the levels it was given", async () => {
    installDom();
    const { renderFan } = await load("ui/analyse-fan.js");
    const svg = renderFan(new Node("div"), fanned());
    const bands = descendants(svg).filter((n) => n._cls?.has("anl-band"));
    assert.deepEqual(bands.map((b) => b.dataset.level), ["90", "80", "70", "60", "50", "40", "30", "20", "10"]);
  });

  it("puts the fan and the curves in the group that opens, and the history outside it", async () => {
    installDom();
    const { renderFan } = await load("ui/analyse-fan.js");
    const svg = renderFan(new Node("div"), fanned());
    const opening = descendants(svg).find((n) => n._cls?.has("anl-opening"));
    assert.match(opening.attrs["clip-path"], /^url\(#anl-open-\d+\)$/);
    const inside = descendants(opening);
    assert.equal(inside.filter((n) => n._cls?.has("anl-band")).length, 9);
    assert.equal(inside.filter((n) => n._cls?.has("anl-path")).length, 3);
    assert.ok(!inside.some((n) => n._cls?.has("anl-history")));
    assert.ok(descendants(svg).some((n) => n._cls?.has("anl-history")), "the closes run into the anchor");
  });

  it("names each curve with its weight, and marks the weight as a figure", async () => {
    installDom();
    const { renderFan } = await load("ui/analyse-fan.js");
    const svg = renderFan(new Node("div"), fanned());
    const labels = descendants(svg).filter((n) => n._cls?.has("anl-plabel"));
    assert.deepEqual(labels.map((l) => l.textContent).sort(), ["Base case 50%", "Bearish 25%", "Bullish 25%"]);
    for (const label of labels) {
      const [name, weight] = label.children;
      assert.ok(name.dataset.chrome, "the name is a label");
      assert.equal(weight.dataset.prov, "derived", "the weight is a figure");
    }
  });

  it("says what the shading is, and that the two sides of the anchor are drawn at two scales", async () => {
    installDom();
    const { renderFan } = await load("ui/analyse-fan.js");
    const host = new Node("div");
    renderFan(host, fanned({ corrected: false, marking: "uncalibrated" }));
    const text = host.textContent;
    assert.match(text, /the middle 10% of the forecast, darkest, out to the middle 90%, in 9 steps/);
    assert.match(text, /This raw width was measured too narrow\./);
    assert.match(text, /Left of the anchor: the last 3 closes\. Right of it: 5 sessions ahead, drawn wider/);
    assert.match(text, /do not know market holidays/);
  });

  it("says a corrected fan was fitted at the horizon only", async () => {
    installDom();
    const { renderFan } = await load("ui/analyse-fan.js");
    const host = new Node("div");
    renderFan(host, fanned());
    assert.match(host.textContent, /fitted at the horizon; between the anchor and the horizon it is carried in proportion/);
  });

  it("states why there is no history rather than drawing none silently", async () => {
    installDom();
    const { renderFan } = await load("ui/analyse-fan.js");
    const host = new Node("div");
    renderFan(host, fanned({ history: null, history_why: "prices were left out of this export" }));
    assert.match(host.textContent, /No price history before the anchor: prices were left out of this export\./);
  });

  it("reads the levels under the pointer, ahead of the anchor and behind it", async () => {
    installDom();
    const { renderFan } = await load("ui/analyse-fan.js");
    const host = new Node("div");
    const svg = renderFan(host, fanned({ anchor: "2026-09-22" }));
    svg.getBoundingClientRect = () => ({ left: 0, width: 1080 });
    const catcher = descendants(svg).find((n) => n._cls?.has("anl-catch"));
    const tip = descendants(host).find((n) => n._cls?.has("anl-tip"));
    catcher._on.pointermove({ clientX: 900 });
    assert.match(tip.textContent, /sessions · ≈ /);
    for (const range of ["median", "50%", "80%", "90%"]) assert.match(tip.textContent, new RegExp(range));
    const marked = descendants(tip).filter((n) => n.dataset?.prov === "derived");
    assert.equal(marked.length, 7, "the median and three ranges, each end a derived figure");
    catcher._on.pointermove({ clientX: 70 });
    assert.match(tip.textContent, /close/);
    assert.equal(descendants(tip).filter((n) => n.dataset?.prov === "measured").length, 1, "a close is measured");
  });

  it("opens once when motion is welcome, and not at all when it is not", async () => {
    installDom();
    const frames = [];
    globalThis.requestAnimationFrame = (fn) => frames.push(fn);
    globalThis.matchMedia = () => ({ matches: false });
    const { renderFan } = await load("ui/analyse-fan.js");
    const svg = renderFan(new Node("div"), fanned());
    const reveal = descendants(svg).find((n) => n.tagName === "RECT" && n.attrs.height && !n._cls?.has("anl-catch"));
    assert.equal(reveal.attrs.width, "0", "closed at the start");
    while (frames.length) frames.shift()(performance.now() + 5000);
    assert.ok(Number(reveal.attrs.width) > 300, "fully open at the end");

    globalThis.matchMedia = () => ({ matches: true });
    frames.length = 0;
    const still = renderFan(new Node("div"), fanned());
    const shut = descendants(still).find((n) => n.tagName === "RECT" && n.attrs.height && !n._cls?.has("anl-catch"));
    assert.notEqual(shut.attrs.width, "0", "reduced motion draws the fan open");
    assert.equal(frames.length, 0, "and asks for no frames");
    delete globalThis.requestAnimationFrame;
    delete globalThis.matchMedia;
  });

  it("colours the bands amber only when the fan is uncalibrated", () => {
    const sheet = read("assets/styles/analyse.css").replace(/\/\*[\s\S]*?\*\//g, "");
    const base = sheet.match(/\.anl-band \{[^}]*\}/)[0];
    assert.doesNotMatch(base, /--uncal/, "a corrected fan is neutral");
    assert.match(sheet, /\.anl-fan\[data-calibration="uncalibrated"\] \.anl-band \{[^}]*var\(--uncal\)/);
  });
});

describe("every custom property a stylesheet reads is defined", () => {
  /* Thirty-three declarations in analyse.css and two in system.css read tokens
     nothing defined — --mono-sm, --sans-sm, --ink-1, --rule-1, --sp-8 — so they
     applied nothing and the analysis screens never looked as written. A var()
     with a fallback is allowed; one without must resolve. */
  it("resolves every var() that has no fallback", () => {
    const dir = new URL("../assets/styles/", import.meta.url);
    const sheets = readdirSync(dir).filter((f) => f.endsWith(".css")).map((f) => [f, readFileSync(new URL(f, dir), "utf8")]);
    const defined = new Set(sheets.flatMap(([, css]) => [...css.matchAll(/(--[a-z0-9-]+)\s*:/g)].map((m) => m[1])));
    for (const [file, css] of sheets) {
      for (const [, name] of css.matchAll(/var\((--[a-z0-9-]+)\s*\)/g)) {
        assert.ok(defined.has(name), `${file} reads ${name}, which nothing defines`);
      }
    }
  });
});
