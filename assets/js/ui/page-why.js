/* The one disclosure, shared by all four screens.

   ONE PER SCREEN, and it is where every sentence goes. A section may carry a
   head, a count and at most one short phrase; anything longer than a phrase is a
   note and belongs here. That is what keeps the working part of a page readable:
   the numbers are on the page and the argument about them is one click away,
   in one place, rather than scattered beside whichever figure prompted it.

   GROUPED BY SECTION, IN PAGE ORDER, so a reader who wants the note about a
   thing they are looking at can find it by position rather than by reading all
   of them. Refusals are their own group — what a screen will not draw is a
   different kind of claim from how to read what it did draw — and the stamps
   note is always last, because it is about the page rather than about any
   section of it.

   PROSE IS MARKED CHROME with its reason. Every note here carries digits that
   are citations, sample sizes and thresholds, not measurements this page
   computed, and the audit has no heuristics to tell those apart. */

import { chrome } from "../lib/figure.js";

const el = (tag, className, text) => {
  const n = document.createElement(tag);
  if (className) n.className = className;
  if (text !== undefined) n.textContent = text;
  return n;
};

/* The last group on every screen. It replaces the sentence that used to sit
   under the footer stamps, where it was printed on every page whether or not
   anyone was asking how to read them. */
export const STAMPS_NOTE = {
  title: "The stamps",
  notes: [
    "Four independent stamps, not one export vintage. Each source dates itself: the " +
      "symbol index is a month older than the prices, and the code stamp is the commit " +
      "that wrote the export rather than the commit that produced the runs inside it.",
  ],
};

/** Build the disclosure.

    `groups` is `[{ title, notes: [string], kind? }]` in page order. `kind:
    "refused"` heads the group in the refusal colour — the word "Refused" is what
    carries it, and the colour only reinforces. The stamps group is appended
    here so no caller can forget it or put it anywhere but last. */
export function renderPageWhy(host, { groups = [] } = {}) {
  host.textContent = "";

  const all = [...groups.filter((g) => g && g.notes && g.notes.length), STAMPS_NOTE];
  const count = all.reduce((n, g) => n + g.notes.length, 0);

  const d = el("details", "page-why");
  const summary = el("summary");
  summary.append(
    el("span", "page-why-caret", "▸"),
    el("span", "page-why-title", "How to read this page"),
  );
  // A count of notes, which is a count and therefore has digits in it.
  const tally = chrome(el("span", "page-why-count", `${count} ${count === 1 ? "note" : "notes"}`),
    "how many notes the disclosure holds");
  summary.append(tally);
  d.append(summary);

  const body = el("div", "page-why-body");
  for (const group of all) {
    const section = el("section", "page-why-group");
    if (group.kind) section.dataset.kind = group.kind;
    const head = el("div", "page-why-head");
    head.append(el("h3", null, group.title));
    // A count or a rate beside the group name, where the note came with one.
    // Chrome, with its reason: these are quoted figures, not measurements.
    if (group.meta) {
      const meta = chrome(el("span", "page-why-meta", group.meta), group.metaWhy ?? "a quoted count beside the note");
      head.append(meta);
    }
    section.append(head);
    for (const note of group.notes) {
      section.append(
        chrome(el("p", null, note), "explanatory prose; its digits are citations, sample sizes and thresholds"),
      );
    }
    body.append(section);
  }
  d.append(body);

  host.append(d);
  return d;
}
