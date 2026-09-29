/* The live-analysis screen — ADR 0036 §1 and §4.

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
    const kids = svg.children;
    const bands = kids.filter((n) => n._cls?.has("anl-band"));
    const paths = kids.filter((n) => n._cls?.has("anl-path"));
    assert.equal(bands.length, 2, "two nested ribbons");
    assert.ok(kids.indexOf(bands[0]) < kids.indexOf(paths[0]), "behind the lines");
  });

  it("takes the axis from the band too, so the ribbon is not clipped", async () => {
    /* The band is usually wider than the three scenarios. An axis fitted to the
       scenarios alone cuts it at the frame and it reads as narrower than it is. */
    installDom();
    const { renderFan } = await load("ui/analyse-fan.js");
    const host = new Node("div");
    renderFan(host, banded());
    const ticks = [...host.children[0].children].filter((n) => n._cls?.has("anl-ytick"));
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
    assert.match(read("assets/js/analyse-page.js"), /RELATIONS\.find\(\(\[v\]\) => v === event\.corpus_relation\)/);
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
    assert.match(prose, /may be one of the filings above or a newer one/);
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
    // Nowhere, on any screen that can offer a run.
    for (const file of ["analyse-page.js", "search-page.js", "ui/analyse-offer.js", "ui/search-box.js"]) {
      assert.doesNotMatch(read(`assets/js/${file}`), /\.disabled = true/, file);
    }
  });

  it("gives every screen the same absence, in the same words", () => {
    /* One module, so the three screens that can offer a run cannot drift into
       three different explanations of the same missing thing. */
    const offer = read("assets/js/ui/analyse-offer.js");
    assert.equal((offer.match(/No analysis server/g) ?? []).length, 1);
    for (const file of ["analyse-page.js", "search-page.js"]) {
      assert.match(read(`assets/js/${file}`), /renderNoServer\(/, file);
      assert.doesNotMatch(read(`assets/js/${file}`), /No analysis server/, file);
    }
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
    for (const file of ["analyse-page.js", "search-page.js", "company.js"]) {
      const page = read(`assets/js/${file}`);
      assert.match(page, /noServerNotes\(\)/, file);
      assert.match(page, /\? \[\] : \[noServerNotes\(\)\]/, `${file} adds them conditionally`);
    }
  });

  it("asks whether a server is there without being able to start a run", () => {
    // `health` with GET. A speculative POST would cost seven minutes to find out.
    const offer = read("assets/js/ui/analyse-offer.js");
    const body = offer.slice(offer.indexOf("export function serverPresent()"));
    assert.match(body.slice(0, 300), /fetch\("health", \{ method: "GET" \}\)/);
  });

  it("probes once per page, not once per row", () => {
    /* A screen with forty readable rows must ask once. A row is never the thing
       that decides whether the feature exists. */
    const offer = read("assets/js/ui/analyse-offer.js");
    assert.match(offer, /probe \?\?= fetch/);
    assert.match(read("assets/js/search-page.js"), /state\.canAnalyse = await serverPresent\(\)/);
    assert.doesNotMatch(read("assets/js/ui/search-box.js"), /serverPresent/);
  });

  it("hands a ticker over as a link rather than posting from the row", () => {
    /* The run belongs to the screen built to show one. Starting seven minutes of
       work from a search row would leave the reader with nowhere to put it. */
    const offer = read("assets/js/ui/analyse-offer.js");
    assert.match(offer, /link\.href = `analyse\.html\?ticker=/);
    assert.doesNotMatch(offer, /method: "POST"/);
  });

  it("seeds an arriving ticker without starting a run", () => {
    const page = read("assets/js/analyse-page.js");
    const boot = page.slice(page.indexOf("async function boot()"));
    assert.match(boot, /params\.get\("ticker"\)/);
    assert.match(boot, /\.anl-input"\)\.value = seeded/);
    // The seeded value fills the box; nothing calls analyse() from boot.
    assert.doesNotMatch(boot, /analyse\(seeded/);
  });

  it("reads the stream as it arrives rather than buffering it", () => {
    /* Buffering would turn a six-minute progress display into a six-minute
       blank, which is the whole reason the response is newline-delimited. */
    const page = read("assets/js/analyse-page.js");
    assert.match(page, /getReader\(\)/);
    assert.match(page, /TextDecoder/);
    assert.doesNotMatch(page, /await response\.text\(\)/);
  });

  it("has a host for every section the module fills", () => {
    const html = read("analyse.html");
    for (const id of ["ground", "masthead-nav", "masthead-vintage", "ask", "progress", "result", "why", "footer"]) {
      assert.match(html, new RegExp(`id="${id}"`), id);
    }
    assert.match(html, /analyse\.css/);
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

  it("is listed in the nav on every screen", () => {
    for (const page of readdirSync(new URL("../", import.meta.url)).filter((f) => f.endsWith(".html"))) {
      assert.match(read(page), /<div id="masthead-nav"><\/div>/, page);
    }
  });
});

describe("a shared component's rules reach every page that renders it", () => {
  /* The defect this exists for: `analyse-offer.js` was rendered from the search
     and company pages while `analyse.css` was linked only from analyse.html, so
     the absence block appeared unstyled — no border, no background, no measure.
     Nothing in the markup was wrong and no test could see it. */
  const OFFER_CLASSES = ["anl-absent", "anl-offer", "anl-periods", "anl-period-note"];
  const PAGES = { "index.html": "search-page.js", "company.html": "company.js", "analyse.html": "analyse-page.js" };

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

  it("and the two really do differ in this export", () => {
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
