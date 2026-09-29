/* This company's next forecast, offered from its own page.

   IT MUST NOT SAY WHICH FILING IT WILL READ. An earlier version told the reader
   the latest 8-K "is not one of the filings above", and for most corpus companies
   that is false: AAPL's most recent Item 2.02 is the 2026-07-30 one sitting in
   the table, and stays so until Q3 arrives. The page cannot know before the run
   which document EDGAR will return, so it says what is true either way and the
   result carries the relation tag the journal would give it (ADR 0036 §2).

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
      "Reads whichever earnings 8-K this company has filed most recently. That may be " +
      "one of the filings above or a newer one, and the result says which. Either way " +
      "it is a new run, recorded on its own terms rather than added to the record on " +
      "this page."),
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
