/* This company's next forecast, offered from its own page.

   It offers the company's LATEST filing, which is a different document from the
   ones the corpus froze — so a run started here is new work, not a re-run of a
   panel item, and the journal will relate it on its own terms rather than being
   told what it is (ADR 0036 §2). The section says so, because a control sitting
   under a table of frozen filings otherwise reads as extending that table.

   With no server the page's one stated absence lands here instead (§4). */

import { chrome } from "../lib/figure.js";
import {
  DEFAULT_HORIZON,
  analyseLink,
  renderHorizons,
  renderNoServer,
  serverPresent,
} from "./analyse-offer.js";

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

export async function renderLive(host, company) {
  host.textContent = "";
  if (!(await serverPresent())) {
    renderNoServer(host, { where: `${company.ticker} cannot be run from this page.` });
    return host;
  }

  const box = el("div", "cmp-live");
  box.append(chrome(el("h3", "cmp-h", "Forecast the latest filing"), "a section heading"));
  box.append(chrome(
    el("p", null,
      "Reads this company's most recent earnings 8-K, which is not one of the filings " +
      "above: those are the ones the corpus froze. A run started here is new work and " +
      "is recorded as such, not added to the record on this page."),
    "what a run from here is",
  ));

  const row = el("div", "cmp-live-row");
  const periods = el("div", "anl-periods-host");
  const link = analyseLink(company.ticker, { horizon: DEFAULT_HORIZON });
  renderHorizons(periods, {
    name: "cmp-horizon",
    selected: DEFAULT_HORIZON,
    // The link carries the choice, so arriving at the screen needs no second pick.
    onPick: (days) => {
      link.href = `analyse.html?ticker=${encodeURIComponent(company.ticker)}&horizon=${days}`;
    },
  });
  row.append(periods, link);
  box.append(row);
  host.append(box);
  return box;
}
