/* The front door — the empty box IS the front door.

   There is no separate landing route and no submit-through. `index.html` was
   already one page (box -> status -> results); the door is that page with an
   empty box, so the first keystroke collapses the crest and the results appear
   in place, and clearing the box is the way back. No navigation either way.

   Mode is two axes, not one. This module owns `door | open`. The index fetch
   phase (`cold | fetching | ready`) is search-box.js's and is independent: you
   can be at the door with the index already loaded, or open and still cold.

   The box and the crest exist TWICE — bare in the door, chromed in the card —
   because one element cannot be in two parents. They carry matching
   `view-transition-name`s (front-door.css), so the browser morphs one into the
   other instead of crossfading. Both stay in the DOM; CSS shows one per mode,
   which keeps the transition names unique among rendered elements and makes
   focus restoration a `.focus()` rather than a remount.

   Everything visual is CSS keyed on `body[data-mode]`, including the rosette's
   scale and opacity. This file only decides the mode and preserves the caret. */

import { DERIVED, chromeText, derive, figure, renderFigure } from "../lib/figure.js";
import { isAbsent } from "../data/source.js";

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

const count = (n) => renderFigure(figure(n, DERIVED, "int"));

/** Masthead nav: three sections, and the crest goes home.

    A company page is NOT a nav item. It is a detail page, reached from a search
    result or a runs row, and an item that needs a subject before it means
    anything would have to pick one — which is how "company" came to link to an
    arbitrary example. `current` is null on such a page: neither section is where
    you are, and nothing is marked.

    "runs", not "run ledger": the rows are runs, and `ledger.items_settled` in
    the export counts corpus items — 709 settled against 779 runs. The contract
    warns against reading one as the other, and a screen's name is where that
    starts. */
export function mountMastheadNav(host, { current }) {
  const nav = el("nav", "nav");
  const items = [
    { key: "search", label: "find a company", href: "index.html" },
    { key: "runs", label: "runs", href: "runs.html" },
    // "results", not "evaluation" or "scores": the screen shows one measurement
    // and its controls, and "scores" is the word the export uses for the records
    // themselves — several of which the screen deliberately does not show.
    { key: "results", label: "results", href: "results.html" },
    // No "live analysis" item. A run is started from the page of the company it
    // is about (ADR 0036, amendment of 2026-09-30), so there is no screen to name.
  ];
  /* Every item is a link, including the current one. The current screen is
     marked with `aria-current`, which the stylesheet draws as a rule rather than
     a colour, so it reads as current in greyscale. It was a <span> before: that
     removed the one place a reader can click to reload a screen they are already
     on, and gave the marked item different hit behaviour from its neighbours. */
  for (const item of items) {
    const a = el("a", null, item.label);
    a.href = item.href;
    if (item.key === current) a.setAttribute("aria-current", "page");
    nav.append(a);
  }
  host.append(nav);
  return nav;
}

/** The door's box and its counts strip, mounted into the static `.door-block`.

    The crest and subtitle are NOT built here; they are markup in index.html. A
    cross-document view transition matches names against the incoming page's
    first rendered frame, and that frame is painted before any module has run —
    so a crest built by this function is not there to be matched, and the morph
    from company.html silently becomes a fade.

    Counts are passed in, never hardcoded, so they stay true to the freeze:
    `companies` from universe.json, `runsBySource` as the boundary reads the
    manifest's four counts (or its absence), and `finding` true only when the
    export carries the development scoring record the finding is stated from. */
export function mountDoor(host, { onQuery, companies, runsBySource, finding, replay = null }) {
  const block = host.querySelector(".door-block");

  const box = el("div", "door-box");
  const input = document.createElement("input");
  input.type = "search";
  input.className = "door-input";
  input.placeholder = "ticker or company name";
  input.autocomplete = "off";
  input.spellcheck = false;
  input.setAttribute("aria-label", "Search ticker or company name");
  box.append(el("span", "door-slash", "/"), input);
  block.append(box);

  /* Each fact is one unbreakable unit, and the separator trails the fact it
     follows: a count never wraps away from its label, and no line of the strip
     can begin with "·" (the strip's CSS says why). */
  const strip = el("div", "door-strip");
  const facts = [];
  const fact = (...parts) => {
    const unit = el("span", "door-fact");
    unit.append(...parts);
    facts.push(unit);
    return unit;
  };
  fact(count(companies), chromeText(" companies", "companies in the frozen corpus"));

  /* The pooling happens HERE, in sight. The manifest carries one count per runs
     file and no total, because the export keeps the four populations apart. A
     door's "N runs" is an inventory of everything recorded — repeats and runs
     outside the corpus included, which is why it is not 701 — so the four are
     added, and derive() marks the sum as computed on this page, not read. */
  if (isAbsent(runsBySource)) {
    fact(chromeText("runs not counted", runsBySource.why));
  } else {
    const perSource = Object.values(runsBySource);
    const total = derive(perSource.reduce((n, f) => n + f.value, 0), "int", ...perSource);
    /* The count is the way in. It is already the thing a reader looks at, and the
       screen it names exists — so it is a link, styled as the text it already was
       rather than as a new element competing with the box. */
    const link = el("a", "door-runs");
    link.href = "runs.html";
    link.title = "Every run in the export";
    link.append(
      renderFigure(total),
      chromeText(" runs recorded", "every run recorded, summed here across the four document sources"),
    );
    fact(link);

    /* "N runs" alone was fine while every run came from the corpus. It is not
       now: live analysis writes runs the panel never asked for, and a reader who
       sees one number next to "120 companies" will read it as work on those
       companies.

       IT SAYS "LIVE RUNS", NOT "OUTSIDE THE CORPUS", because those are different
       sets and this count is the smaller one. `corpus_relation` calls five runs
       `outside_corpus` today — the one live run plus four AAPL runs that predate
       the document-source field — and this clause can only see the sources the
       manifest counts. Labelling a count of live runs with the name of a larger
       set would put a number on the door that the runs screen contradicts. */
    const live = ["edgar", "news"]
      .map((key) => runsBySource[key])
      .filter((figure) => figure && figure.value > 0);
    if (live.length) {
      const sum = derive(live.reduce((n, f) => n + f.value, 0), "int", ...live);
      fact(
        renderFigure(sum),
        chromeText(
          sum.value === 1 ? " live run" : " live runs",
          "runs made on demand from this machine, counted per document source in the manifest",
        ),
      );
    }
  }

  /* Stated for the development companies only, because that is the half an
     exported file backs: scores/*.dev.* carries both rules against both
     baselines with their intervals. The holdout's comparison survives as a
     sentence and no figure (M.A.P. Findings #57), so the line does not reach it,
     and without the development record it is not stated at all. */
  if (finding) {
    fact(chromeText(
      "does not beat a plain random walk or GARCH on the development companies",
      "stated from the exported development scoring record, where neither baseline is beaten on CRPS or log score",
    )).className = "door-fact door-fact--sentence";
  }
  facts.forEach((unit, i) => {
    if (i < facts.length - 1) unit.append(el("span", "door-dot", "·"));
    strip.append(unit);
  });

  /* The foot: the recorded run's line above the counts, in one box, so the two
     cannot overlap however the counts wrap. */
  const foot = el("div", "door-foot");

  /* The path to the recorded run. On a copy with no models this is the only way
     to see what an analysis produces, and it used to have a nav item of its own;
     now it lives on the company's page, so the door names it once. Only when the
     export carries one — the link names the run the manifest pins, never a
     hardcoded company. */
  if (replay && !isAbsent(replay)) {
    const line = el("div", "door-replay");
    const a = el("a", "door-replay-link");
    a.href = `company.html?ticker=${encodeURIComponent(replay.ticker)}#live`;
    a.append(
      chromeText("A recorded live run: ", "what the link leads to"),
      chromeText(`${replay.ticker}, ${replay.anchor_date}`, "the recorded run's company and date"),
      chromeText(" →", "a link arrow"),
    );
    line.append(a);
    foot.append(line);
  }
  foot.append(strip);
  host.append(foot);

  input.addEventListener("input", () => onQuery(input.value));
  return { input };
}

/** The controller. `doorInput` and `pageInput` are the two boxes.

    `sync(query)` is called at the end of every paint of the search page — after
    the results DOM is updated, because a view transition snapshots the page as
    it stands when the mode flips. It is idempotent and cheap when the mode does
    not change, so calling it on every keystroke is correct. */
export function createModeController({ doorInput, pageInput }) {
  const modeFor = (query) => (query.trim() ? "open" : "door");

  /* Focus moves to the box the new mode shows, and it moves INSIDE the flip.
     Waiting for the transition's `ready` leaves a frame in which the box being
     typed into is display:none and a keystroke lands on <body>: typed at 60 ms a
     key, "TSLA" arrived as "TSA". The value is carried across from the box that
     had focus, because a keystroke that arrived after the last paint is in that
     box and nowhere else yet. */
  const restore = (mode) => {
    const [from, to] = mode === "open" ? [doorInput, pageInput] : [pageInput, doorInput];
    if (!to) return;
    if (from && document.activeElement === from) to.value = from.value;
    to.focus();
    const n = to.value.length;
    try { to.setSelectionRange(n, n); } catch { /* type=search in some engines */ }
  };

  return {
    /** Mirror `query` into both boxes, then flip the mode inside a view
        transition if it changed. Without the API the flip is an instant swap. */
    sync(query) {
      const next = modeFor(query);
      if (doorInput && doorInput.value !== query) doorInput.value = query;
      if (pageInput && pageInput.value !== query) pageInput.value = query;
      if (document.body.dataset.mode === next) return next;

      const flip = () => {
        document.body.dataset.mode = next;
        restore(next);
      };
      if (document.startViewTransition) document.startViewTransition(flip);
      else flip();
      return next;
    },

    /** Focus whichever box the current mode shows. At boot that is the door's:
        the page's box is display:none there, and focusing it does nothing. */
    focus() {
      restore(document.body.dataset.mode);
    },
  };
}
