/* The CSS blind spot, closed.

   `node --test tests/*.test.mjs` builds the DOM against a stub and never loads a
   stylesheet. That is the right trade for the unit suite — it runs in
   milliseconds, needs no browser and passes with the inference server off — but
   it means a whole class of defect is invisible to it, and two have shipped:

     system.css loaded BEFORE the per-screen sheets, so `.cmp-h` in company.css
     outranked the shared section-head voice and the restyle did nothing;

     company.html never linked runs.css at all, so the journal rows it had just
     adopted rendered as unstyled overlapping blocks.

   Both passed 140 tests. Neither is a pixel problem — each is a STRUCTURAL one:
   a stylesheet that did not load, or loaded in the wrong order. So this is not a
   pixel diff. It opens each page in a real browser and asserts a handful of
   computed values that can only be right if the right sheets loaded in the right
   order, plus two whole-page invariants:

     every <link rel=stylesheet> actually parsed (catches a 404 or a missing one)
     system.css is LAST (catches the shared system being outranked)

   WHY IT IS NOT IN THE UNIT SUITE. It needs a browser, and Playwright is
   deliberately not a dependency of this repository — it would put a 300 MB
   install behind `uv run pytest`. It resolves from outside instead, and says so
   clearly when it cannot. A machine without it skips this check; CI, if it ever
   runs one, installs Playwright and runs it.

     node tests/styles.probe.mjs
     PLAYWRIGHT_PATH=/path/to/node_modules/playwright node tests/styles.probe.mjs

   Exit 0 all passed · 1 a check failed · 2 could not run (no Playwright). */

import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { extname, join, normalize } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = fileURLToPath(new URL("../", import.meta.url));

const TYPES = {
  ".html": "text/html", ".css": "text/css", ".js": "text/javascript",
  ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png",
};

/** A static server, written here rather than depended on: the point of this file
    is to need nothing the repository does not already have. */
function serve() {
  const server = createServer(async (req, res) => {
    const path = normalize(decodeURIComponent(req.url.split("?")[0]));
    // No traversal above the served root, even from a local probe.
    const file = join(ROOT, path === "/" ? "index.html" : path);
    if (!file.startsWith(ROOT) || !existsSync(file)) {
      res.writeHead(404).end("not found");
      return;
    }
    try {
      res.writeHead(200, { "content-type": TYPES[extname(file)] ?? "application/octet-stream" });
      res.end(await readFile(file));
    } catch (err) {
      res.writeHead(500).end(String(err));
    }
  });
  return new Promise((ok) => server.listen(0, "127.0.0.1", () => ok(server)));
}

/** Resolve Playwright from outside the repository.

    `PLAYWRIGHT_PATH` may point at the package directory, which ESM `import()`
    will not resolve on its own — it takes a specifier or a file URL, not a
    folder. So a directory is tried as its two possible entry points before
    falling back to a bare specifier, which works when Playwright is installed
    globally or reachable through NODE_PATH. */
async function playwright() {
  const attempts = [];
  const dir = process.env.PLAYWRIGHT_PATH;
  if (dir) {
    attempts.push(pathToFileURL(join(dir, "index.mjs")).href);
    attempts.push(pathToFileURL(join(dir, "index.js")).href);
    attempts.push(pathToFileURL(dir).href);
  }
  attempts.push("playwright");

  for (const spec of attempts) {
    try {
      const mod = await import(spec);
      if (mod?.chromium || mod?.default?.chromium) return mod.chromium ? mod : mod.default;
    } catch { /* try the next */ }
  }
  return null;
}

/* ---- the checks ------------------------------------------------------ */
/* Each is a property whose value is WRONG, not merely different, when a
   stylesheet is missing or outranked. Where a token is involved the expected
   value is read from the token rather than written down, so a token change is
   not a false failure. */

const MONO = /JetBrains Mono/;
const SERIF = /Newsreader/;

const PAGES = [
  /* "A", not a whole ticker: the row check needs a group with MORE THAN ONE row
     in it, because the first row in a group deliberately has no rule above it.
     On "AAPL" the corpus group holds one row and the check read its own special
     case as a failure. */
  { url: "index.html", type: "A", checks: ["shell", "search", "oneRing"] },
  { url: "company.html?ticker=AAPL", checks: ["shell", "journalRows", "table"] },
  { url: "runs.html", checks: ["shell", "journalRows", "cardSurface"] },
  { url: "results.html", checks: ["shell", "cardSurface", "expandRows", "headWidth"] },
];

/** Run inside the page. Returns raw readings; the assertions are outside, so a
    failure message can say what it wanted and what it got. */
function readPage() {
  const cs = (sel) => {
    const el = document.querySelector(sel);
    return el ? getComputedStyle(el) : null;
  };
  const token = (name) =>
    getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  const links = [...document.querySelectorAll('link[rel="stylesheet"]')].map((l) => l.getAttribute("href"));
  const parsed = [...document.styleSheets].map((s) => {
    let rules = -1;
    try { rules = s.cssRules.length; } catch { rules = -1; }
    return { href: s.href ? new URL(s.href).pathname.replace(/^\//, "") : null, rules };
  });

  const head = cs(".cmp-h, .section-h, .runs-card > header h2, .res-card > header h2");
  const title = cs(".page-title");
  const crest = cs(".masthead h1");
  const nav = cs(".nav");
  const tag = cs(".tag");
  /* NOT the first row. The first journal row on both pages is a re-based one,
     which carries a deliberate red tint, and the first search row in a group
     deliberately has no top rule. Picking a representative element rather than
     the first is the difference between a check and a coincidence. */
  const row = cs('.runs-row:not([data-drift="true"])');
  const card = cs(".res-card, .runs-card");
  const summary = cs(".res-row > summary");
  /* The forest plots must start at ONE x. Each comparison row is its own
     <details>, so their grids do not align automatically; a content-sized column
     moved the plot, and with the plot on 1fr that moved the ZERO RULE drawn at
     its middle. Three zero lines at three x is not a forest plot. */
  const plotLefts = [...document.querySelectorAll(".res-plot")]
    .map((el) => Math.round(el.getBoundingClientRect().left));

  const left = (sel) => {
    const el = document.querySelector(sel);
    return el ? Math.round(el.getBoundingClientRect().left) : null;
  };
  const right = (sel) => {
    const el = document.querySelector(sel);
    return el ? Math.round(el.getBoundingClientRect().right) : null;
  };

  /* The disclosure sits in the page frame like every other section. On two
     screens it was a sibling of <main> rather than a child, so it never got the
     gutter and its caret sat on the screen edge. */
  const gutter = {
    why: left(".page-why"),
    section: left("main > section, main > div"),
  };

  /* The results head holds the same grid the charts do. It was `id="identity"`,
     which company.css caps at the prose measure — the same collision that once
     made the runs header narrow — so it stopped 236px short of the plots. */
  const frame = { head: right("#res-identity .res-identity"), grid: right(".res-row-1") };

  /* A table's header and its cells share a left edge. components.css
     right-aligns every td as a default for numeric tables, and this one holds
     dates, bands, accession numbers and ids. */
  const firstRow = document.querySelector(".cmp-table tbody tr");
  const table = firstRow && {
    th: [...document.querySelectorAll(".cmp-table th")].map((t) => Math.round(t.getBoundingClientRect().left)),
    td: [...firstRow.children].map((t) => Math.round(t.getBoundingClientRect().left)),
    tdAlign: [...firstRow.children].map((t) => getComputedStyle(t).textAlign),
  };

  /* ONE focus ring. The box draws it; the input inside it must not draw a
     second, or one control reads as two. */
  /* The VISIBLE box. index.html keeps the door in the DOM and hides it with
     CSS, and the door's markup comes first — so a plain querySelector focused a
     `display: none` input, which can never match :focus-visible and so could
     never show a second ring. The check passed by testing nothing. */
  const boxInput = [...document.querySelectorAll(".srch-box input, .door-box input")]
    .find((el) => el.getClientRects().length > 0) ?? null;
  let ring = null;
  if (boxInput) {
    boxInput.focus();
    const box = boxInput.closest(".srch-box, .door-box");
    ring = {
      inputOutline: getComputedStyle(boxInput).outlineStyle,
      inputBorder: getComputedStyle(boxInput).borderStyle,
      boxBorder: getComputedStyle(box).borderStyle,
    };
  }
  const srow = cs(".srch-row:not(:first-of-type)");
  const srowCount = document.querySelectorAll(".srch-row").length;

  return {
    links,
    parsed,
    tokens: { sp6: token("--sp-6"), step2: token("--step-2"), ink2: token("--ink-2") },
    head: head && {
      fontFamily: head.fontFamily, textTransform: head.textTransform,
      letterSpacing: head.letterSpacing, fontSize: head.fontSize,
    },
    title: title && { fontFamily: title.fontFamily },
    crest: crest && { fontFamily: crest.fontFamily, fontSize: crest.fontSize, textTransform: crest.textTransform },
    nav: nav && { display: nav.display, columnGap: nav.columnGap },
    tag: tag && { fontFamily: tag.fontFamily, borderTopWidth: tag.borderTopWidth, borderTopStyle: tag.borderTopStyle },
    row: row && { gridTemplateColumns: row.gridTemplateColumns, display: row.display, backgroundColor: row.backgroundColor },
    card: card && { backgroundColor: card.backgroundColor, borderTopWidth: card.borderTopWidth },
    plotLefts, gutter, frame, table, ring,
    summary: summary && { display: summary.display, gridTemplateColumns: summary.gridTemplateColumns },
    srowCount,
    srow: srow && { borderTopStyle: srow.borderTopStyle, backgroundColor: srow.backgroundColor },
  };
}

const failures = [];
const ok = (page, name, cond, want, got) => {
  if (cond) return;
  failures.push(`${page} · ${name}\n      wanted ${want}\n      got    ${got}`);
};

function assertShell(page, r) {
  /* Every linked sheet parsed. A 404 or a sheet nobody linked is the whole of
     the company.html/runs.css defect, and this is the cheapest way to see it. */
  for (const href of r.links) {
    const sheet = r.parsed.find((s) => s.href === href);
    ok(page, `stylesheet loaded: ${href}`, sheet && sheet.rules > 0,
      "parsed, with rules", sheet ? `${sheet.rules} rules` : "not in document.styleSheets");
  }

  /* system.css LAST. It is the shared system for all four screens, and when it
     loaded before the per-screen sheets every shared rule lost silently. */
  const sheets = r.parsed.filter((s) => s.href).map((s) => s.href);
  ok(page, "system.css is the last stylesheet", sheets.at(-1) === "assets/styles/system.css",
    "assets/styles/system.css last", sheets.at(-1) ?? "none");

  // The section-head voice. THE exact rule company.css used to outrank.
  ok(page, "section head is mono", r.head && MONO.test(r.head.fontFamily),
    "a mono stack", r.head?.fontFamily ?? "no section head found");
  ok(page, "section head is uppercase", r.head?.textTransform === "uppercase",
    "uppercase", r.head?.textTransform);
  ok(page, "section head is tracked", parseFloat(r.head?.letterSpacing) > 2,
    "> 2px of tracking (.32em)", r.head?.letterSpacing);

  ok(page, "page title is serif", r.title && SERIF.test(r.title.fontFamily),
    "a serif stack", r.title?.fontFamily ?? "no .page-title");
  ok(page, "crest is serif", r.crest && SERIF.test(r.crest.fontFamily),
    "a serif stack", r.crest?.fontFamily ?? "no crest");
  ok(page, "crest is not the old uppercase sans", r.crest?.textTransform === "none",
    "none", r.crest?.textTransform);
  ok(page, "crest is --step-2", r.crest?.fontSize === px(r.tokens.step2),
    px(r.tokens.step2), r.crest?.fontSize);

  ok(page, "nav is a flex row", r.nav?.display === "flex", "flex", r.nav?.display);
  ok(page, "nav gap is --sp-6", r.nav?.columnGap === px(r.tokens.sp6),
    `${px(r.tokens.sp6)} (--sp-6)`, r.nav?.columnGap);

  ok(page, "tag is mono", r.tag && MONO.test(r.tag.fontFamily),
    "a mono stack", r.tag?.fontFamily ?? "no .tag on this page");
  ok(page, "tag has a 1px solid border", r.tag?.borderTopWidth === "1px" && r.tag?.borderTopStyle === "solid",
    "1px solid", `${r.tag?.borderTopWidth} ${r.tag?.borderTopStyle}`);

  // The disclosure is in the frame, not beside it.
  ok(page, "the disclosure shares the page gutter", r.gutter.why !== null && r.gutter.why === r.gutter.section,
    `left ${r.gutter.section} (a section's)`, `left ${r.gutter.why}`);
}

function assertHeadWidth(page, r) {
  ok(page, "the head reaches the chart grid's right edge", r.frame.head !== null && r.frame.head === r.frame.grid,
    `right ${r.frame.grid} (the grid's)`, `right ${r.frame.head}`);
}

function assertTable(page, r) {
  ok(page, "the filings table has rows to check", r.table !== null, "a tbody row", "none");
  if (!r.table) return;
  ok(page, "every header sits on its column", String(r.table.th) === String(r.table.td),
    `th lefts ${r.table.th}`, `td lefts ${r.table.td}`);
  ok(page, "cells read from the left, like their headers",
    r.table.tdAlign.every((a) => a === "left" || a === "start"),
    "every cell left", r.table.tdAlign.join(", "));
}

function assertOneRing(page, r) {
  ok(page, "the search box has an input to focus", r.ring !== null, "an input in the box", "none");
  if (!r.ring) return;
  // The BOX is the control. Two rings on one control read as two controls.
  ok(page, "the input draws no second ring", r.ring.inputOutline === "none" && r.ring.inputBorder === "none",
    "no outline and no border on the input",
    `outline ${r.ring.inputOutline}, border ${r.ring.inputBorder}`);
  ok(page, "the box draws the ring", r.ring.boxBorder === "solid", "solid", r.ring.boxBorder);
}

function assertJournalRows(page, r) {
  /* runs.css. Without it `.runs-row` is a <button> with no grid at all, which is
     exactly how the company page shipped for one commit. */
  ok(page, "journal row is a grid", r.row?.display === "grid", "grid", r.row?.display ?? "no .runs-row");
  const tracks = (r.row?.gridTemplateColumns ?? "").split(/\s+/).filter(Boolean).length;
  ok(page, "journal row has its columns", tracks >= 8,
    ">= 8 tracks (caret, anchored, id, relation, freeze, hzn, two closes, realised)",
    `${tracks} tracks: ${r.row?.gridTemplateColumns}`);
  // A <button> defaults to a filled background. The sheet clears it.
  ok(page, "journal row has no button fill", /rgba\(0, 0, 0, 0\)|transparent/.test(r.row?.backgroundColor ?? ""),
    "transparent", r.row?.backgroundColor);
}

function assertCardSurface(page, r) {
  // The shared pass strips card fills. If system.css is outranked they come back.
  ok(page, "section card has no fill", /rgba\(0, 0, 0, 0\)|transparent/.test(r.card?.backgroundColor ?? ""),
    "transparent", r.card?.backgroundColor ?? "no card");
  ok(page, "section card is separated by a rule", r.card?.borderTopWidth === "1px",
    "1px", r.card?.borderTopWidth);
}

function assertExpandRows(page, r) {
  ok(page, "comparison row summary is a grid", r.summary?.display === "grid",
    "grid", r.summary?.display ?? "no .res-row > summary");
  ok(page, "the six comparison rows exist", r.plotLefts.length === 6,
    "6 plots", `${r.plotLefts.length}`);
  const lefts = new Set(r.plotLefts);
  ok(page, "every forest plot starts at the same x", lefts.size === 1,
    "one left edge, so the zero rules line up", `${lefts.size} distinct: ${[...lefts].join(", ")}`);
}

function assertSearch(page, r) {
  // The check is about SEPARATION, so it needs two rows to separate. Asserted
  // rather than skipped: a query that stopped matching would otherwise turn this
  // into a check that silently tests nothing.
  ok(page, "the query matched enough rows to check separation", r.srowCount > 1,
    "> 1 result row", `${r.srowCount} rows`);
  ok(page, "result rows are hairline-separated", r.srow?.borderTopStyle === "solid",
    "solid", r.srow?.borderTopStyle ?? "no non-first .srch-row");
  ok(page, "result rows are not boxed", /rgba\(0, 0, 0, 0\)|transparent/.test(r.srow?.backgroundColor ?? ""),
    "transparent", r.srow?.backgroundColor);
}

const ASSERTIONS = {
  shell: assertShell, journalRows: assertJournalRows, cardSurface: assertCardSurface,
  expandRows: assertExpandRows, search: assertSearch, headWidth: assertHeadWidth,
  table: assertTable, oneRing: assertOneRing,
};

/** A token's value as the browser reports a length: `0.75rem` is not `12px`, and
    the comparison has to be in the unit getComputedStyle answers in. */
function px(token) {
  const rem = parseFloat(token);
  return token.endsWith("rem") ? `${rem * 16}px` : token;
}

/* ---- run ------------------------------------------------------------- */
const pw = await playwright();
if (!pw) {
  console.error(
    "styles.probe: Playwright is not installed, and it is deliberately not a\n" +
    "dependency of this repository. Install it OUTSIDE the repo and point at it:\n\n" +
    "  mkdir -p ~/tools/pw && cd ~/tools/pw && npm i playwright && npx playwright install chromium\n" +
    "  PLAYWRIGHT_PATH=~/tools/pw/node_modules/playwright node tests/styles.probe.mjs\n",
  );
  process.exit(2);
}

const server = await serve();
const base = `http://127.0.0.1:${server.address().port}`;
const browser = await pw.chromium.launch();
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });

let checked = 0;
for (const spec of PAGES) {
  const page = await context.newPage();
  await page.goto(`${base}/${spec.url}`, { waitUntil: "networkidle" });
  // index.html is the door until something is typed; the nav and the page are
  // only mounted in the open state.
  if (spec.type) await page.keyboard.type(spec.type, { delay: 20 });
  await page.waitForTimeout(spec.type ? 1200 : 900);

  const reading = await page.evaluate(readPage);
  for (const name of spec.checks) {
    ASSERTIONS[name](spec.url, reading);
    checked += 1;
  }
  await page.close();
}

await browser.close();
server.close();

if (failures.length) {
  console.error(`\nstyles.probe: ${failures.length} check(s) failed\n`);
  for (const f of failures) console.error(`  ✖ ${f}\n`);
  process.exit(1);
}
console.log(`styles.probe: ${PAGES.length} pages, ${checked} groups, all computed styles as expected`);
