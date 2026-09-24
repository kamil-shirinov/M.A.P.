/* The funnel, and the one disclosure.

   Three counts, three files, three moments — that is the spine, and the two
   drops between them mean different things. What the export can and cannot
   count is part of the reading:

     120     counted at boot from universe.json.
     10,398  counted the moment symbols.json is open.
     5,309   NOT IN THE EXPORT. No file states it and the manifest does not
             carry it; it comes from the export contract's own funnel. So it is
             not a figure and is not rendered as one — it is marked as chrome
             naming where it came from. Counting it here would mean a pass over
             filers.json's ticker lists, which this page does not make. */

import { DERIVED, chrome, chromeText, figure, renderFigure } from "../lib/figure.js";

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

function stage({ n, quoted, what, share, file, when, width, tone, prov, provWhy }) {
  const row = el("div", "srch-stage");
  row.dataset.tone = tone;

  const big = el("div", "srch-stage-n");
  big.append(n === null ? chromeText(quoted, provWhy) : count(n));

  const mid = el("div", "srch-stage-mid");
  mid.append(
    prose(el("div", "srch-stage-what", what), "the stage label; any digits are a form designation"),
    prose(el("div", "srch-stage-share", share), "shares and counts quoted from the export contract"),
  );

  const src = el("div", "srch-stage-src");
  src.append(chromeText(file, "the file this count comes from, and its size"), el("div", "srch-stage-when", when));

  const chip = el("span", "srch-prov");
  chip.dataset.prov = prov;
  chip.append(chromeText(prov, provWhy));

  const bar = el("div", "srch-bar");
  const fill = el("i");
  fill.style.width = width;
  bar.append(fill);

  row.append(big, mid, src, chip);
  const wrap = el("div", "srch-stage-wrap");
  wrap.append(row, bar);
  return wrap;
}

function drop(nText, why) {
  const d = el("div", "srch-drop");
  d.append(chromeText(nText, "the difference between two stages of the funnel"), document.createTextNode(" " + why));
  return prose(d, "explanatory prose; its digits are a form designation and a quoted drop");
}

export function renderFunnel(host, { symbolCount }) {
  host.textContent = "";
  const head = el("div", "srch-head");
  head.append(
    prose(
      el("h2", "cmp-h", "From every listed symbol to the frozen 120"),
      "a section heading; 120 is the corpus size",
    ),
    el("span", "srch-note", "three numbers, three sources, three moments"),
  );
  host.append(head);

  host.append(
    stage({
      n: symbolCount,
      quoted: "index not read",
      provWhy: "the index size is not known until symbols.json is open",
      what: "symbols in the index",
      share: "every listed symbol, including preferred lines, ADRs and dual classes",
      file: "symbols.json · 864 KB",
      when: "on the first keystroke",
      width: "100%",
      tone: "top",
      prov: symbolCount === null ? "not read" : "counted",
    }),
  );
  host.append(
    drop("−5,089", "tickers whose filer has no Item 2.02 in its recent block. Nothing for M.A.P. to read, and no run would change that."),
  );
  host.append(
    stage({
      n: null,
      quoted: "5,309",
      provWhy: "from the export contract's funnel; no file in this export states it",
      what: "on a filer that publishes earnings 8-Ks",
      share: "51.1% of symbols · 4,325 of 7,998 filers, which is 54.1%",
      file: "filers.json · 1.2 MB",
      when: "opened only when a hit falls outside the corpus",
      width: "51.1%",
      tone: "mid",
      prov: "quoted",
    }),
  );
  host.append(
    drop("−5,189", "tickers that publish the document and have not been read. Readable, outside the freeze, and not queued for anything."),
  );
  host.append(
    stage({
      n: 120,
      quoted: "",
      provWhy: "counted from universe.json, which loads at boot",
      what: "in the frozen corpus",
      share: "1.2% of symbols · 709 filings, 779 runs",
      file: "universe.json · 7.5 KB",
      when: "at boot",
      width: "1.2%",
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
    meta: "5,189 tickers, quoted from the contract",
    metaWhy: "from the export contract's funnel; no file in this export states it",
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
    meta: "3,673 of 7,998 filers · 45.9%",
    metaWhy: "from the export contract's funnel; no file in this export states it",
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

export function renderWhy(host) {
  host.textContent = "";
  const d = el("details", "srch-why cmp-disclosure");
  const s = el("summary");
  s.append(
    el("span", "srch-why-caret", "▸"),
    el("span", "srch-why-title", "Why a symbol resolves the way it does"),
    el("span", "srch-note", "three outcomes, two refusals, and how to read the three counts"),
  );
  d.append(s);

  const body = el("div", "srch-why-body");
  for (const r of RESOLUTIONS) {
    const card = el("div", "srch-res");
    const head = el("div", "srch-res-head");
    head.append(el("h3", "cmp-h3", r.title), chromeText(r.meta, r.metaWhy));
    card.append(head);
    r.paras.forEach((p) =>
      card.append(prose(el("p", "cmp-note", p), "explanatory prose; its digits are citations and quoted counts")),
    );
    body.append(card);
  }

  const ref = el("div", "cmp-refusals srch-res");
  ref.append(el("div", "srch-res-kicker", "Two things this box will not say"));
  const ul = el("ul");
  for (const [head, text] of REFUSALS) {
    const li = el("li");
    li.append(el("strong", null, head + " "), document.createTextNode(text));
    prose(li, "explanatory prose; its digits are quoted counts and a file size");
    ul.append(li);
  }
  ref.append(ul);
  body.append(ref);

  /* Moved off the page: both paragraphs are good and both sat under a visual
     that already makes the point. */
  const counts = el("div", "srch-res srch-res--counts");
  counts.append(el("div", "srch-res-kicker", "Reading the three counts"));
  const p1 = el("p", "cmp-note");
  p1.append(
    el("strong", null, "51.1% of tickers, 54.1% of filers. "),
    document.createTextNode(
      "The two rates are not one figure reported twice. A single filer can carry many tickers: " +
        "Connecticut Light & Power files under one CIK and appears in the index thirteen times, as " +
        "preferred lines. Counting tickers weights those thirteen; counting filers counts them once. " +
        "The search box counts tickers, because a ticker is what gets typed into it.",
    ),
  );
  const p2 = el("p", "cmp-note");
  p2.append(
    el("strong", null, "The middle number is the expensive one. "),
    document.createTextNode(
      "The corpus count is read at boot from a 7.5 KB file. The index count is known the moment " +
        "the index lands. The readable count needs filers.json at 1.2 MB, which this page opens only " +
        "when a hit falls outside the corpus — and even then it answers one ticker at a time, so the " +
        "total is quoted from the export contract rather than counted here.",
    ),
  );
  prose(p1, "explanatory prose; the rates are quoted from the export contract");
  prose(p2, "explanatory prose; the sizes and counts are quoted from the export contract");
  counts.append(p1, p2);
  body.append(counts);

  d.append(body);
  host.append(d);
}
