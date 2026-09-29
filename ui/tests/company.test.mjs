/* The company page, rendered against the REAL export.

   A DOM stub rather than jsdom: the repository has no build step and no
   dependencies, and the sections use a narrow slice of the DOM. The stub is
   enough to run them and to walk the result, which is what the provenance audit
   needs — the audit is the point of these tests, since it is the rule the page
   most easily breaks. */

import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { before, describe, it } from "node:test";
import { HAVE_EXPORT, itNeedsExport } from "./needs-export.mjs";
import { Node, installDom } from "./dom.mjs";

const EXPORT = new URL("../assets/export/", import.meta.url);
const HAVE = existsSync(new URL("manifest.json", EXPORT));

/* ---- a DOM small enough to read and large enough to render into ---- */


function stubFetch() {
  globalThis.fetch = async (path) => {
    const name = String(path).replace(/^assets\/export\//, "");
    if (!existsSync(new URL(name, EXPORT))) return { status: 404, ok: false };
    return { status: 200, ok: true, json: async () => JSON.parse(readFileSync(new URL(name, EXPORT), "utf8")) };
  };
}

/** Every text node with a digit must sit inside a marked ancestor. This is the
    page's own rule, reimplemented over the stub tree. */
function unmarkedNumbers(root) {
  const bad = [];
  const walk = (node) => {
    if (node.nodeType === 3) {
      if (/\d/.test(node.data) && !node.parentElement?.closest("[data-prov], [data-chrome], [data-audit-exempt]")) {
        bad.push(node.data.trim());
      }
      return;
    }
    if (node._text && /\d/.test(node._text) && !node.closest("[data-prov], [data-chrome], [data-audit-exempt]")) {
      bad.push(node._text.trim());
    }
    node.children?.forEach(walk);
  };
  walk(root);
  return bad;
}

const load = (m) => import(`../assets/js/${m}?${Math.random()}`);

async function renderCompany(ticker, { openRuns = true } = {}) {
  installDom();
  stubFetch();
  const source = await load("data/source.js");
  const [company, runs, series, scoring, state] = await Promise.all([
    source.getCompany(ticker), source.listRuns(ticker), source.getPriceSeries(ticker),
    source.listScoringRecords(), source.getExportState(),
  ]);
  const roots = {};
  const mk = () => new Node("section");
  const { renderIdentity } = await load("ui/company-identity.js");
  const { renderSeries } = await load("ui/company-series.js");
  const { renderFilings } = await load("ui/company-filings.js");
  const { renderRuns } = await load("ui/company-runs.js");
  const { renderScoring } = await load("ui/company-scoring.js");
  const { renderFooter } = await load("ui/company-footer.js");

  renderIdentity((roots.identity = mk()), { company, runs });
  renderSeries((roots.series = mk()), { series, runs });
  renderFilings((roots.filings = mk()), { company, runs });
  /* The runs are journal rows now, and the detail a card printed inline lives in
     the expanded body. These assertions are about that content, so the default
     here is every row open. A test that wants the collapsed row passes false. */
  const open = new Set(
    openRuns ? Object.values(runs.bySource).flat().map((r) => r.run_id) : [],
  );
  renderRuns((roots.runs = mk()), { runs, company, open, onToggle: () => {} });
  renderScoring((roots.scoring = mk()), { scoring, company });
  renderFooter((roots.footer = mk()), state.manifest);

  /* The page's notes, as the foot disclosure renders them. Several assertions
     below are about sentences that moved off the page and into it; they should
     check the sentence still exists somewhere, not that it vanished. */
  const { renderPageWhy } = await load("ui/page-why.js");
  const { COMPANY_WHY } = await load("ui/company-why.js");
  const whyRoot = mk();
  renderPageWhy(whyRoot, { groups: COMPANY_WHY });
  return { roots, company, runs, source, why: whyRoot.textContent };
}

/** Every element in a rendered tree, in order. */
function* walk(node) {
  yield node;
  for (const child of node.children ?? []) if (child.nodeType !== 3) yield* walk(child);
}

describe("company page, against the real export", () => {
  for (const ticker of ["ACHC", "ATI", "AAPL"]) {
    itNeedsExport(`${ticker}: every number on screen is marked`, async () => {
      const { roots } = await renderCompany(ticker);
      for (const [name, root] of Object.entries(roots)) {
        assert.deepEqual(unmarkedNumbers(root), [], `${ticker}/${name} has unmarked numbers`);
      }
    });
  }

  itNeedsExport("ACHC is the plain page: no drift, no repeat, no open window", async () => {
    const { runs, source } = await renderCompany("ACHC");
    const rows = Object.values(runs.bySource).flat();
    assert.equal(rows.length, 6);
    assert.ok(rows.every((r) => r.corpus_relation === "ledger_item"));
    assert.ok(rows.every((r) => r.outcome_status === "closed"));
    assert.ok(rows.every((r) => source.isAbsent(r.anchor_drift)));
  });

  itNeedsExport("ATI shows a repeat whose panel run does not exist", async () => {
    const { roots, company } = await renderCompany("ATI");
    const text = roots.runs.textContent;
    assert.match(text, /whose panel run does not exist/);
    assert.match(text, /not because a run exists and is shown elsewhere/);
    // And the filings table mirrors it without linking back.
    assert.match(roots.filings.textContent, /held, not run/);
    assert.equal(company.filings.filter((f) => !f.ran).length, 2);
  });

  itNeedsExport("AAPL shows drift and an open window, and keeps the outcome", async () => {
    const { roots } = await renderCompany("AAPL");
    const text = roots.runs.textContent;
    assert.match(text, /re-based since this run/);
    assert.match(text, /0\.988142|1\.007509/, "the ratio is shown at six places");
    assert.match(text, /horizon has not elapsed yet/);
    // A drifted run keeps its outcome; the marker is what stops the two from
    // looking identical.
    assert.match(text, /Closed at/);
    /* The claim survives the card-to-row change, said once instead of twice. The
       card had `describeDrift`'s "This outcome is not part of any published
       score" AND a tail repeating it; the row keeps the first. */
    assert.match(text, /not part of any published score/);
  });

  itNeedsExport("no run is both drifted and open, so that drift tail never renders", async () => {
    // The spec gives the drift block two tails, one for a closed outcome and one
    // for an open window. All 9 drifted runs are closed and both open runs are
    // undrifted, so the open-window tail is unreachable against this export. The
    // branch stays -- a later export can reach it -- and this pins the fact.
    const { runs, source } = await renderCompany("AAPL");
    const rows = Object.values(runs.bySource).flat();
    const drifted = rows.filter((r) => !source.isAbsent(r.anchor_drift));
    assert.ok(drifted.length > 0);
    assert.ok(drifted.every((r) => r.outcome_status === "closed"));
    assert.ok(rows.filter((r) => r.outcome_status === "window_open")
      .every((r) => source.isAbsent(r.anchor_drift)));
  });

  itNeedsExport("refuses the two renderings, in the disclosure rather than silently", async () => {
    /* These were two cards under the scoring section. They are refusals, and the
       shared system gives every screen's refusals one group in the page-foot
       disclosure — so they are still stated, in the same words, in the place a
       reader goes for what a screen will not draw. */
    const { why } = await renderCompany("ACHC");
    assert.match(why, /Not scored/);
    assert.match(why, /would claim that scored-eligible runs went unscored/);
    assert.match(why, /map_sigma but no p10, p50 or p90/);
    assert.match(why, /modelling presented as reading/);
  });

  itNeedsExport("shows the clean-band record, and names the other band as a control", async () => {
    /* `identified[0]` picked whichever record sorted first. When the ambiguous
       band was scored it sorted ahead of clean by filename, which would have put
       an ambiguous record under copy about clean-band scope. */
    const { roots, source } = await renderCompany("ACHC");
    const { identifiable } = await source.listScoringRecords();
    const clean = identifiable.find((r) => r.band === "clean");
    const text = roots.scoring.textContent;

    // Four mono rows now, in the same wording Results uses.
    assert.match(text, new RegExp(`clean · development${"[^]*"}${clean.n} items`));
    assert.match(text, new RegExp(`code ${clean.forecast_digest.slice(0, 8)}`));

    const control = identifiable.find((r) => r.band !== "clean");
    if (control) {
      assert.match(text, new RegExp(`${control.band}[^]*${control.n} items · separate record`));
      // The control is a different population, never more of the first.
      assert.ok(!new RegExp(`${control.n} items · code`).test(text), "the control is not the record");
    }
    // The holdout row states both halves: its terms survive, its scores do not.
    assert.match(text, /holdout · 173 items · scored once/);
    assert.match(text, /none exist — never persisted, unrecoverable by design/);
  });

  itNeedsExport("never prints a per-run score", async () => {
    const { roots } = await renderCompany("ACHC");
    for (const word of ["CRPS", "crps", "PIT", "Brier", "log score"]) {
      assert.doesNotMatch(roots.runs.textContent, new RegExp(word), `${word} appeared on a run card`);
    }
  });

  itNeedsExport("shows the exchange, which the corpus row now carries", async () => {
    /* It read "not loaded" while the search screen's chip said INDEX LOADED and
       the ticker was plainly in it — true in a narrow sense and useless to read.
       `map export` copies the field onto corpus.json, which this page opens
       anyway, so the absence is gone rather than better explained. */
    const { roots, why } = await renderCompany("ACHC");
    assert.doesNotMatch(roots.identity.textContent, /not loaded/);
    assert.match(roots.identity.textContent, /Nasdaq|NYSE|NYSE American|Cboe|OTC/);
    assert.match(why, /corpus\.json, which this page already opens/);
  });

  itNeedsExport("names the page a record rather than a projection", async () => {
    const { roots, why } = await renderCompany("ACHC");
    /* This moved from a paragraph under the fact strip into the disclosure, and
       the strip gained two facts that make the same point without a sentence:
       CLOSED n of n, and LIVE FORECAST none in export. */
    assert.match(roots.identity.textContent, /Live forecast/i);
    assert.match(roots.identity.textContent, /none in export/);
    assert.match(why, /record of forecasts already made/);
    assert.match(why, /not a current projection/);
  });

  itNeedsExport("draws a y-axis, and marks every level as derived", async () => {
    /* This test used to assert the OPPOSITE — that the section drew no ticks —
       on the grounds that a tick would be a figure with no provenance. That held
       while the series was a fixture. The closes are real now, so a level
       between the lowest and highest of them is computed from measured inputs,
       which is what `derived` means. The axis is allowed; what is not allowed is
       an unmarked one. */
    const { roots } = await renderCompany("ACHC");
    const ticks = [...walk(roots.series)].filter((n) => n._cls?.has("cmp-ytick"));
    assert.ok(ticks.length >= 3, `expected an axis, found ${ticks.length} ticks`);
    for (const t of ticks) {
      assert.equal(t.dataset.prov, "derived", "a level the page chose is derived, not measured");
      assert.match(t.textContent, /^[\d,]+\.\d\d$/, `a tick reads as a price: ${t.textContent}`);
    }
    /* Emitted low to high, which puts the largest at the top of the plot because
       y is inverted. The order that matters is that they are monotonic — an axis
       with a level out of sequence is worse than no axis. */
    const values = ticks.map((t) => Number(t.textContent.replace(/,/g, "")));
    assert.deepEqual(values, [...values].sort((a, b) => a - b), "levels are monotonic");
    assert.equal(new Set(values).size, values.length, "and distinct");
    // And every one of them is inside the data, not invented beyond it.
    const src = await load("data/source.js");
    const series = await src.getPriceSeries("ACHC");
    const closes = series.sessions.map((b) => b[1]);
    const lo = Math.min(...closes), hi = Math.max(...closes);
    for (const v of values) assert.ok(v >= lo && v <= hi, `${v} is outside [${lo}, ${hi}]`);
  });

  itNeedsExport("carries filing_date from the ledger, not derived from the anchor", async () => {
    const { runs } = await renderCompany("ACHC");
    const rows = Object.values(runs.bySource).flat();
    const withItem = rows.filter((r) => r.ledger_item && !r.ledger_item.absent);
    assert.ok(withItem.length > 0);
    assert.ok(withItem.some((r) => r.ledger_item.filing_date !== r.anchor_date));
  });

  itNeedsExport("keeps the four run files apart", async () => {
    const { runs } = await renderCompany("AAPL");
    assert.deepEqual(Object.keys(runs.bySource).sort(), ["corpus", "edgar", "news", "unknown"]);
  });
});

describe("colour discipline", () => {
  const css = readFileSync(new URL("../assets/styles/company.css", import.meta.url), "utf8");

  itNeedsExport("reserves amber for a number that is not a settled measurement", () => {
    /* ACROSS EVERY STYLESHEET, not just this one. Scoped to company.css this
       assertion passed while amber quietly acquired four meanings elsewhere: a
       provenance chip on search, an in-flight fetch beside it, and an
       instruction about which way to read an axis on results. None of those is
       a claim about a value, and a colour that means four things is decoration.

       What amber means now is one thing said two ways: the uncalibrated state
       (a forecast whose horizon is outside what was validated) and work that was
       attempted and did not complete (the missing panel run, a filing held but
       never run). Both are "this number is not settled". */
    const ALLOWED = /cmp-panel-missing|cmp-unrun|data-calibration="uncalibrated"|data-tone="uncal"/;
    const sheets = readdirSync(new URL("../assets/styles/", import.meta.url))
      .filter((f) => f.endsWith(".css") && f !== "tokens.css");
    assert.ok(sheets.length >= 6, "every stylesheet is read, not just this page's");

    for (const name of sheets) {
      const sheet = readFileSync(new URL(`../assets/styles/${name}`, import.meta.url), "utf8")
        .replace(/\/\*[\s\S]*?\*\//g, "");
      const amberRules = sheet
        .split("}")
        .filter((block) => /var\(--uncal/.test(block))
        .map((block) => block.split("{")[0].trim());
      for (const selector of amberRules) {
        assert.match(
          selector,
          ALLOWED,
          `amber on ${selector} in ${name} -- it means "not a settled measurement"`,
        );
      }
    }
  });

  itNeedsExport("does not colour an open window as an attention state", () => {
    // A fact about the calendar: nothing is wrong, nothing refused, and it
    // resolves by itself. Distinguished by the dash, not by colour.
    const openRules = css.split("}").filter((b) => /cmp-anchor--open|window_open/.test(b.split("{")[0] ?? ""));
    assert.ok(openRules.length >= 3);
    for (const rule of openRules) {
      assert.doesNotMatch(rule, /var\(--uncal|var\(--down/, `open-window rule uses an alarm colour: ${rule}`);
    }
    assert.match(css, /cmp-anchor--open \{[^}]*stroke-dasharray/);
  });
});

describe("run identity on every card", () => {
  itNeedsExport("shows an abbreviated run_id on all of them, not just collisions", async () => {
    const { roots, runs } = await renderCompany("AAPL");
    const rows = Object.values(runs.bySource).flat();
    const text = roots.runs.textContent;
    for (const run of rows) {
      assert.ok(text.includes(run.run_id.slice(0, 8)), `no id shown for ${run.run_id}`);
    }
  });

  itNeedsExport("distinguishes same-anchor runs, which are common rather than rare", async () => {
    // 62 (ticker, anchor, horizon) groups corpus-wide hold more than one run.
    // AAPL has three such pairs; without an id the cards are indistinguishable.
    const { runs } = await renderCompany("AAPL");
    const rows = Object.values(runs.bySource).flat();
    const seen = new Map();
    for (const r of rows) {
      const key = `${r.anchor_date}|${r.horizon_days}`;
      seen.set(key, (seen.get(key) ?? 0) + 1);
    }
    const collisions = [...seen.values()].filter((n) => n > 1).length;
    assert.equal(collisions, 3);
    assert.equal(new Set(rows.map((r) => r.run_id)).size, rows.length);
  });
});

describe("layout invariants", () => {
  const css = readFileSync(new URL("../assets/styles/company.css", import.meta.url), "utf8");

  itNeedsExport("gives the masthead, content and footer one measure", () => {
    // They sat at different left edges: the masthead outside any container and
    // the content capped, so the difference read as dead space.
    assert.match(css, /\.masthead,\s*\n\s*\.company,\s*\n\s*\.cmp-footer \{[^}]*--measure/);
  });

  itNeedsExport("anchors the vintage stamps right without relying on a spacer element", () => {
    // base.css does this with a .spacer that this page's markup does not have.
    assert.match(css, /\.masthead-vintage \{ margin-left: auto/);
  });

  itNeedsExport("gives section headers a voice of their own, and a rule above them", () => {
    /* This used to demand --step-2 and forbid --step--1: a section head earned
       presence by being bigger than the body. The shared pass gets it a
       different way — mono, uppercase and tracked to .32em, which is the door's
       tagline voice — so the head is SMALLER than the body and still unmistakably
       a head. The rule above it, which was always half the answer, survives.

       The voice lives in system.css and the box stays in company.css, so the
       four screens cannot drift apart on what a section head looks like. */
    const system = readFileSync(new URL("../assets/styles/system.css", import.meta.url), "utf8");
    const voice = system.match(/\.cmp-h,[\s\S]*?\{[^}]*\}/)[0];
    assert.match(voice, /font-family: var\(--font-mono\)/);
    assert.match(voice, /text-transform: uppercase/);
    assert.match(voice, /letter-spacing: \.32em/);

    const box = css.match(/\.cmp-h \{[^}]*\}/)[0];
    assert.match(box, /border-top/, "a section still announces itself with a rule");
    assert.doesNotMatch(box, /font-size/, "the size belongs to the shared voice, not to this page");
  });
});

describe("the pre-screen is a search question", () => {
  itNeedsExport("does not appear on a company page", async () => {
    const { roots } = await renderCompany("ACHC");
    for (const root of Object.values(roots)) {
      assert.doesNotMatch(root.textContent, /recent EDGAR block/);
      assert.doesNotMatch(root.textContent, /Item 2\.02 8-Ks/);
    }
  });

  itNeedsExport("is still reachable from the boundary, for the screen that needs it", async () => {
    installDom();
    stubFetch();
    const source = await load("data/source.js");
    const screen = await source.getFilerScreen("AAPL");
    assert.equal(typeof screen.item_202_in_recent, "boolean");
  });
});

describe("URL forms", () => {
  const js = readFileSync(new URL("../assets/js/company.js", import.meta.url), "utf8");

  itNeedsExport("accepts ?ticker= as the linked form and keeps ?example= for review", () => {
    assert.match(js, /params\.get\("ticker"\)/);
    assert.match(js, /params\.get\("example"\)/);
  });

  itNeedsExport("marks a ticker link as linked, never as an example name", () => {
    // Styling keyed on an example must not silently apply to an arbitrary
    // company reached from search.
    assert.match(js, /mode: "linked"/);
    assert.match(js, /dataset\.example = mode/);
  });

  itNeedsExport("renders a stated absence for a ticker the corpus does not hold", () => {
    // CD's patch header said the identity section already handled this. It did
    // not: renderIdentity prints undefined and renderFilings throws on
    // company.filings. The guard is in the composition root instead.
    assert.match(js, /source\.isAbsent\(company\)/);
    assert.match(js, /function renderUnknownCompany/);
    assert.doesNotMatch(
      js.slice(js.indexOf("onToggle:"), js.indexOf("renderScoring")),
      /function renderUnknownCompany/,
      "the handler must be at module level, not inside a callback",
    );
  });
});

describe("the four screen defects", () => {
  const css = readFileSync(new URL("../assets/styles/company.css", import.meta.url), "utf8");

  itNeedsExport("resolves a repeat's panel run by anchor, not by filing arithmetic", async () => {
    // TSLA's 2026-01-02 filing is one of the 66 whose anchor IS the filing date.
    // A `filing + 1` rule found nothing there and printed ATI's copy about a
    // panel run that does not exist, while a9b0c9d8 sat in the filings table on
    // the same page.
    const { roots } = await renderCompany("TSLA");
    const text = roots.runs.textContent;
    assert.doesNotMatch(text, /filing not identified/);
    assert.doesNotMatch(text, /whose panel run does not exist/);
    assert.match(text, /the panel's run is a9b0c9d8, anchored 2026-01-02/);
  });

  itNeedsExport("still reports the one repeat whose panel run really is absent", async () => {
    const { roots } = await renderCompany("ATI");
    assert.match(roots.runs.textContent, /filed 2026-02-03, whose panel run does not exist/);
  });

  itNeedsExport("names the two different run counts rather than showing one", async () => {
    // Search counts panel runs from corpus.json; this page counts every run for
    // the ticker. TSLA is 12 and 16. Unlabelled they read as a contradiction.
    const { roots, runs, company } = await renderCompany("TSLA");
    const panel = company.filings.reduce((n, f) => n + f.run_ids.length, 0);
    const all = Object.values(runs.bySource).flat().length;
    assert.equal(panel, 12);
    assert.equal(all, 16);
    assert.match(roots.identity.textContent, /Panel runs/);
    assert.match(roots.identity.textContent, /Runs on this page/);
  });

  itNeedsExport("colours neither half of the split", () => {
    // Accent means panel membership, and dev and holdout are both the panel.
    // Same overloading that took clean/ambiguous neutral.
    assert.doesNotMatch(css, /\.cmp-badge--holdout \{/);
    assert.doesNotMatch(css, /\.cmp-badge--dev \{/);
    const base = css.match(/\.cmp-badge \{[^}]*\}/)[0];
    assert.doesNotMatch(base, /var\(--accent/);
  });

  itNeedsExport("gives the badge an outline that survives the row it sits on", () => {
    // The dev text measured 6.62:1 and was never the problem: the border was
    // --rule-2, about 1.3:1 on a sunken row, so the badge had no shape.
    const base = css.match(/\.cmp-badge \{[^}]*\}/)[0];
    assert.match(base, /border: 1px solid var\(--ink-3\)/);
    assert.doesNotMatch(base, /border: 1px solid var\(--rule-2\)/);
  });

  itNeedsExport("centres the unknown-company state instead of pinning it to the top", () => {
    const empty = css.match(/\.cmp-empty \{[^}]*\}/)[0];
    assert.match(empty, /min-height/);
    assert.match(empty, /justify-content: center/);
  });
});

describe("a re-based run has no realised return, on any screen", () => {
  /* A re-based run is one whose pinned snapshot disagrees with the spot the run
     recorded, because the provider applied a corporate action between them. Its
     outcome close is split-adjusted and its anchor spot is not, so dividing one
     by the other produces a number with two price bases in it.

     On AAPL's two 2026-08-13 runs that quotient is 2.7% — 311.30 over 302.98.
     It is not the return the forecast was scored against and it is not a return
     that happened to anybody. The runs journal always refused it; the company
     page printed it, so the same run read 2.7% on one screen and x1.007509 on
     the other. This pins BOTH screens, because the defect was the disagreement
     as much as the number. */

  /* This file walks trees by text rather than by class, so it has no byClass.
     One is needed here: the assertion is about one element's content, and a
     whole-page text search would pass on a page that printed both the refusal
     and the number. */
  const byClass = (root, cls) => [...walk(root)].filter((n) => n._cls?.has(cls));

  const drifted = (runs, source) =>
    Object.values(runs.bySource).flat().filter((r) => !source.isAbsent(r.anchor_drift));

  itNeedsExport("finds the runs this is about, so the test cannot pass by finding none", async () => {
    const { runs, source } = await renderCompany("AAPL");
    const bad = drifted(runs, source);
    assert.equal(bad.length, 2, "AAPL carries the two 2026-08-13 re-based runs");
    for (const run of bad) {
      // The quotient the page used to print, so the assertions below have a
      // concrete string to refuse rather than "no percentage anywhere".
      assert.ok(!source.isAbsent(run.outcome), "both are closed, which is why it printed");
      assert.equal(run.anchor_drift.ratio.value.toFixed(6), "1.007509");
    }
  });

  itNeedsExport("shows the ratio and no realised figure on the company page", async () => {
    const { roots, runs, source } = await renderCompany("AAPL");
    const bad = drifted(runs, source);

    /* The realised CELL of each re-based row. This is the assertion that matters:
       a whole-page text search would pass on a page that printed both the ratio
       and the percentage, which is exactly what the cards used to do. */
    const rows = byClass(roots.runs, "runs-row").filter((r) => r.dataset.drift === "true");
    assert.equal(rows.length, bad.length, "both re-based runs are rows");
    for (const row of rows) {
      const cell = byClass(row, "runs-c-real")[0];
      assert.match(cell.textContent, /^×\d\.\d{6}$/, "the ratio, and only the ratio");
      assert.ok(!/%/.test(cell.textContent), "no realised percentage");
    }

    // And the expanded body says why, in the same words the journal uses.
    const bodies = byClass(roots.runs, "runs-detail");
    const rebased = bodies.filter((p) => /No realised return is shown/.test(p.textContent));
    assert.equal(rebased.length, bad.length, "every re-based run says why it has no figure");
    for (const p of rebased) assert.match(p.textContent, /it would mix two price bases/);

    /* The ratio is what exists, and it is still on the page. This page states it
       in prose — "the snapshot closes 305.26 ... against 302.98 recorded
       (1.007509)" — where the journal's column shows ×1.007509. Both are the
       same measured value; the assertion is on the number, not on its wrapper,
       so it survives the row rewrite in spec 02. */
    const text = roots.runs.textContent;
    assert.match(text, /1\.007509/, "the ratio is shown in the re-based block");
    assert.match(text, /305\.26 at this anchor against 302\.98 recorded/, "both bases are named");

    // And the runs that are NOT re-based still show theirs: the refusal is
    // scoped to the defect, not a blanket removal.
    const ordinary = byClass(roots.runs, "runs-row")
      .filter((r) => r.dataset.drift !== "true")
      .map((r) => byClass(r, "runs-c-real")[0].textContent)
      .filter((t) => /%/.test(t));
    assert.ok(ordinary.length >= 5, "ordinary runs keep their realised return");
  });

  itNeedsExport("agrees with the runs journal, which is where the rule came from", () => {
    // Both screens reach the same conclusion from the same field, in the same
    // words, so a reader moving between them sees one fact rather than two.
    const card = readFileSync(new URL("../assets/js/ui/company-runs.js", import.meta.url), "utf8");
    const journal = readFileSync(new URL("../assets/js/ui/runs-journal.js", import.meta.url), "utf8");
    for (const src of [card, journal]) {
      assert.match(src, /No realised return is shown/, "the refusal is stated on screen, not silent");
    }
    // The journal refuses it in the row as well as in the expanded detail.
    assert.match(journal, /No realised figure on a re-based row/);
  });
});
