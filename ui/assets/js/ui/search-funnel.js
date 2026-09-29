/* The funnel, and the one disclosure.

   Three counts, three files, three moments — that is the spine, and the two
   drops between them mean different things.

     120     counted at boot from universe.json.
     10,398  counted the moment symbols.json is open.
     5,309   counted at EXPORT time and carried in the manifest.

   The middle number used to be quoted from the export contract, because counting
   it in the browser means a pass over filers.json at 1.2 MB and this page opens
   that file only when a hit falls outside the corpus. So the count moved to where
   both files are already open: `map export` walks them once and writes the
   funnel into the manifest, and the page reads integers at boot. All three stages
   are now counted, and none is quoted.

   ONE BASE, and it is TICKERS. The middle stage carried two rates — 51.1% of
   symbols beside 54.1% of filers — and two rates on one line read as one figure
   reported twice. They are not: a single filer can carry thirteen tickers, so the
   two weight the same world differently. A ticker is what gets typed into the
   box, so every share on this screen is over 10,398 and the filer count appears
   only in the disclosure, as the note explaining why the choice matters. */

import { DERIVED, MEASURED, chrome, chromeText, derive, figure, renderFigure } from "../lib/figure.js";

/* See search-box.js: prose carrying digits is marked with the reason they are
   there, because the audit cannot tell a citation or a quoted count from a
   figure this page computed. */
const prose = (node, why) => chrome(node, why);

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

const count = (n) => renderFigure(figure(n, DERIVED, "int"));

/* The manifest's funnel, read from the file rather than computed here, so the
   stage counts are MEASURED and the rates over them are DERIVED. */
const measured = (n) => figure(n, MEASURED, "int");
const shareOf = (n, base) =>
  renderFigure(derive(n / base, "pct", measured(n), measured(base)));

function stage({ n, quoted, what, share, file, when, width, tone, prov, provWhy }) {
  const row = el("div", "srch-stage");
  row.dataset.tone = tone;

  const big = el("div", "srch-stage-n");
  big.append(n === null ? chromeText(quoted, provWhy) : count(n));

  const mid = el("div", "srch-stage-mid");
  const line = el("div", "srch-stage-share");
  /* The share is built from figures now rather than written as a sentence, so
     the audit sees a marked rate instead of prose that happens to hold digits.
     A stage with nothing to say about its share gets an empty line, not chrome
     standing in for a number that was never computed.

     `share` is a list of GROUPS, not of nodes: a figure and the label naming its
     base belong together, and the separator goes between groups. Flattened, the
     base row read "100.0% · of tickers". */
  if (share) {
    share.forEach((group, i) => {
      if (i) line.append(chromeText(" · ", "a separator between two readings of one stage"));
      group.forEach((part) => line.append(part));
    });
  }
  mid.append(
    prose(el("div", "srch-stage-what", what), "the stage label; any digits are a form designation"),
    line,
  );

  const src = el("div", "srch-stage-src");
  src.append(chromeText(file, "the file this count comes from, and its size"), el("div", "srch-stage-when", when));

  // The shared tag component. QUOTED keeps the dashed border it was given when
  // amber was narrowed: a provenance is a stroke, and the dash is the same dash
  // the quoted mark uses on a number.
  const chip = el("span", "srch-prov tag");
  chip.dataset.prov = prov;
  chip.append(chromeText(prov, provWhy));

  const bar = el("div", "srch-bar");
  const fill = el("i");
  fill.style.width = width;
  fill.classList.add("enter-span");
  fill.style.transformOrigin = "left";
  bar.append(fill);

  row.append(big, mid, src, chip);
  const wrap = el("div", "srch-stage-wrap");
  wrap.append(row, bar);
  return wrap;
}

/** One mono line between two bars. The full sentence — why those tickers drop
    out, and whether a later run could change it — is in the disclosure, word for
    word. A bordered block for a half-sentence made the drop look like a warning
    about the funnel rather than a step in it. */
function drop(nText, why) {
  const d = el("div", "srch-drop");
  d.append(chromeText(nText, "the difference between two stages of the funnel"), document.createTextNode(" " + why));
  return prose(d, "explanatory prose; its digits are a form designation and a quoted drop");
}

/** The label beside a rate, so a bare percentage never floats without its base. */
const over = (text) => chromeText(text, "names the base a share is taken over");

export function renderFunnel(host, { symbolCount, funnel }) {
  /* No funnel block means an export written before `map export` counted one. The
     stages still render from what this page can see; the shares do not, because a
     share needs a base and inventing one would be worse than an empty line. */
  const f = funnel ?? null;
  const base = f?.tickers ?? null;
  const share = (n) => (base && Number.isFinite(n) ? [[shareOf(n, base), over(" of tickers")]] : null);

  host.textContent = "";
  const head = el("div", "srch-head");
  head.append(
    prose(
      el("h2", "cmp-h", "From every listed symbol to the frozen 120"),
      "a section heading; 120 is the corpus size",
    ),
  );
  host.append(head);

  host.append(
    stage({
      n: symbolCount,
      quoted: "index not read",
      provWhy: "the index size is not known until symbols.json is open",
      what: "symbols in the index",
      // The sentence about preferred lines, ADRs and dual classes is in the
      // disclosure: it explains why the number is larger than a count of
      // companies, which is a note rather than a reading of the bar.
      // The base is its own 100%, which is worth stating rather than implying.
      share: share(base),
      file: "symbols.json · 864 KB",
      when: "on first keystroke",
      width: "100%",
      tone: "top",
      prov: symbolCount === null ? "not read" : "counted",
    }),
  );
  host.append(
    drop(f ? `−${f.no_earnings_filings.toLocaleString("en-US")}` : "−5,089",
      "do not publish earnings results this way"),
  );
  host.append(
    stage({
      n: f?.earnings_filer ?? null,
      quoted: "not counted",
      provWhy: "this export carries no funnel block, so the count is not available",
      what: "on a filer that publishes earnings 8-Ks",
      share: share(f?.earnings_filer),
      file: "filers.json · 1.2 MB",
      when: "counted at export",
      width: base ? `${((f.earnings_filer / base) * 100).toFixed(1)}%` : "51.1%",
      tone: "mid",
      prov: f ? "counted" : "not counted",
    }),
  );
  host.append(
    drop(f ? `−${f.readable_unread.toLocaleString("en-US")}` : "−5,189",
      "publish them, and M.A.P. has not read them"),
  );
  host.append(
    stage({
      n: f?.frozen ?? 120,
      quoted: "",
      provWhy: "counted from universe.json, which loads at boot",
      what: "in the frozen corpus",
      share: share(f?.frozen ?? 120),
      file: "universe.json · 7.5 KB",
      when: "at boot",
      width: base ? `${(((f.frozen ?? 120) / base) * 100).toFixed(1)}%` : "1.2%",
      tone: "bottom",
      prov: "counted",
    }),
  );
}

const RESOLUTIONS = [
  {
    title: "In the frozen corpus",
    meta: "120 companies · 60 dev · 60 holdout",
    metaWhy: "companies in the frozen corpus, counted from universe.json",
    paras: [
      "The corpus holds this company's filings and the runs that read them, each run with its " +
        "scenarios and its outcome, and the page for it is a record of forecasts already made. " +
        "This is the only resolution with a destination, because it is the only one with anything to show.",
      "A corpus hit never opens filers.json. Whether the company publishes earnings 8-Ks is already " +
        "settled by the filings that were read, so the row shows the split and the counts the corpus " +
        "holds and asks nothing further. Its exchange stays absent: that field is in the symbol index.",
    ],
  },
  {
    title: "Files earnings, and M.A.P. has not read it",
    meta: "readable_unread",
    metaWhy: "counted at export from filers.json and the symbol index",
    paras: [
      "Item 2.02 is the document M.A.P. reads, so a filer carrying one is readable. It has not been " +
        "read: the corpus was frozen and this company is not in it.",
      "There is no page, and this browser cannot make one. What you are reading is a directory of " +
        "static files — there is nothing behind it to accept a request, so nothing is queued, pending " +
        "or retrying. Reading it would be a run on a machine with the model on it, and it would appear " +
        "in a later freeze.",
      "The word recent names a block of the filer's filing history, not a calendar window. A filer that " +
        "stopped reporting three years ago can still answer true with a most-recent date in 2023. The row " +
        "prints the date it has.",
    ],
  },
  {
    title: "No earnings filings to read",
    meta: "no_earnings_filings",
    metaWhy: "counted at export from filers.json and the symbol index",
    paras: [
      "The count of Item 2.02 filings in the recent block is zero and there is no most-recent date. " +
        "M.A.P. reads earnings 8-Ks, so for this filer there is nothing to read rather than something " +
        "left unread. That is a fact about how the company reports, and it does not change when the " +
        "corpus is next extended.",
      "It does not say never filed: the block is the recent slice of a filer's history, not the whole " +
        "of it, and the export never claims to have looked further back. The flag is read only where the " +
        "pre-screen's status is ok.",
    ],
  },
];

const REFUSALS = [
  [
    "“No matches.”",
    "Not while the index is in flight. Before symbols.json lands the box can see 120 companies and " +
      "nothing else, and calling a symbol absent on that basis would turn a fetch still in progress " +
      "into a false negative. The wording changes only when the file is open.",
  ],
  [
    "“Run a forecast.”",
    "There is no server to ask. A static export cannot accept the request, so no button offers it and " +
      "no row is marked pending. The thing that produces a run is a command on a machine with the " +
      "model on it; this is the record of the ones that already happened.",
  ],
];

/** The notes this screen contributes to the page-foot disclosure.

    The three resolution outcomes keep their own groups and their quoted rates;
    the two refusals become the "Refused" group, where the word carries the claim
    and the colour only reinforces it; and the paragraph about reading the three
    counts becomes the last section group, before the stamps.

    Content is unchanged from the card layout this replaces. What changed is that
    it is now one disclosure on every screen rather than a different one per
    screen with a different name. */
export function whyGroups(funnel = null) {
  /* The three resolution metas are counts over the ticker base, so they come from
     the manifest rather than from a string written when the numbers were quoted.
     A meta naming a funnel key is filled here; anything else is literal. */
  const pct = (n) => `${((n / funnel.tickers) * 100).toFixed(1)}%`;
  const fill = (meta) =>
    funnel && meta in funnel
      ? `${funnel[meta].toLocaleString("en-US")} of ${funnel.tickers.toLocaleString("en-US")} tickers · ${pct(funnel[meta])}`
      : meta in { readable_unread: 1, no_earnings_filings: 1 }
        ? "not counted in this export"
        : meta;
  return [
    {
      title: "Find a company",
      notes: [
        "Matched on ticker prefix, then on company name. A term that is a whole ticker resolves " +
          "to that ticker first.",
        "The export is not ranked: an exact ticker comes first, then alphabetical order, because " +
          "nothing in these files states which symbol you meant.",
        "At most 24 outside-corpus hits are screened per term. The pre-screen answers one filer " +
          "at a time and a broad term can match hundreds, so the screen is capped and the cap is " +
          "stated rather than hidden behind a spinner.",
      ],
    },
    {
      title: "Exchange",
      notes: [
        "Not loaded, rather than unknown. A corpus row's exchange lives in symbols.json, and " +
          "opening 864 KB to label a row is the eager cost the export splits the two files to " +
          "avoid. The row says which it is.",
      ],
    },
    ...RESOLUTIONS.map((r) => ({
      title: r.title,
      meta: fill(r.meta),
      metaWhy: r.metaWhy,
      notes: r.paras,
    })),
    {
      title: "Refused",
      kind: "refused",
      notes: REFUSALS.map(([head, text]) => `${head} ${text}`),
    },
    {
      title: "From every listed symbol",
      notes: [
        "10,398 is every listed symbol, including preferred lines, ADRs and dual classes. It is " +
          "not a count of companies, which is why it is larger than any count of companies you " +
          "will see elsewhere.",
        "The first drop is the tickers whose filer has no Item 2.02 in its recent block. Nothing " +
          "for M.A.P. to read, and no run would change that.",
        "The second is the tickers that publish the document and have not been read. Readable, " +
          "outside the freeze, and not queued for anything.",
      ],
    },
    {
      title: "Reading the three counts",
      notes: [
        "Every share on this screen is over one base: tickers, all 10,398 of them, because a " +
          "ticker is what gets typed into the box. The stages used to carry a second base beside " +
          "it — 51.1% of symbols next to 54.1% of filers — and two rates on one line read as one " +
          "figure reported twice. They are not. A single filer can carry many tickers: " +
          "Connecticut Light & Power files under one CIK and appears in the index thirteen times, " +
          "as preferred lines. Counting tickers weights those thirteen; counting filers counts " +
          "them once.",
        "The filer-side numbers, for anyone who wants them: 4,325 of 7,998 filers publish Item " +
          "2.02, which is 54.1%. That is a different question from the one this screen answers, " +
          "and it is stated here rather than on a bar so the two cannot be read as one.",
        "Filers are not rows. filers.json holds 8,001 rows over 7,998 distinct filers: three CIKs " +
          "appear twice, a pre-screen request that failed followed by the retry that succeeded. " +
          "The last row for a CIK is the one that counts, and all three retries came back with no " +
          "Item 2.02 in the block.",
        "All three stage counts are counted, none quoted. The middle one is the expensive one — it " +
          "needs filers.json at 1.2 MB, which this page opens only when a hit falls outside the " +
          "corpus, and even then one ticker at a time. So it is counted where both files are " +
          "already open: `map export` walks them once and writes the funnel into the manifest, and " +
          "this page reads integers at boot.",
        "None of the parts is a subtraction. The tickers a freeze did not take are counted as " +
          "such, not as the readable count minus 120 — a subtraction would still balance if a " +
          "corpus ticker were missing from the index, and the screen would report a drop that " +
          "never happened. The four parts sum to the base exactly.",
      ],
    },
  ];
}
