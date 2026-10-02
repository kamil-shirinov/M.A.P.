import { figure, renderFigure, chromeText } from "../lib/figure.js";
import { MIN_N_FOR_A_RATE } from "../data/fixtures/reliability.js";

/* Rows only. No summary row, and deliberately no coverage rate: with two or
   three filings a company, a rate here would be an interval spanning most of
   the unit line — the meaningless statistic this project exists to avoid.

   PIT leads and the band hit follows, because a column of ticks and crosses
   invites the reader to count them and form "2 of 3" by eye — reconstructing
   exactly the number we are declining to print. A continuous PIT is meaningful
   per row and does not aggregate in the head. */

export function renderTrackRecord(host, { record, provenance }) {
  host.textContent = "";
  const rows = record.forecasts;

  if (!rows.length) {
    const p = document.createElement("p");
    p.className = "empty";
    p.textContent = "No scored forecast for this company yet.";
    host.append(p);
    return;
  }

  const table = document.createElement("table");
  const thead = document.createElement("thead");
  const hr = document.createElement("tr");
  for (const h of ["Forecast date", "Spot", "Stated 10–90%", "Realised", "PIT", "In band"]) {
    const th = document.createElement("th");
    // Column headings are marked as chrome, not left to a heuristic: "Stated
    // 10–90%" contains digits and is a label, and the audit is given no way to
    // guess which is which.
    th.append(chromeText(h, "column heading"));
    hr.append(th);
  }
  thead.append(hr);
  table.append(thead);

  const tbody = document.createElement("tbody");
  for (const f of rows) {
    const tr = document.createElement("tr");

    const d = document.createElement("td");
    d.append(chromeText(f.as_of, "forecast date"));

    const spot = document.createElement("td");
    spot.append(renderFigure(figure(f.spot_price, provenance, "price")));

    const band = document.createElement("td");
    band.append(renderFigure(figure(f.stated.p10, provenance, "pctSigned")));
    band.append(chromeText(" to ", "range separator"));
    band.append(renderFigure(figure(f.stated.p90, provenance, "pctSigned")));

    const real = document.createElement("td");
    real.append(renderFigure(figure(f.realised.return, provenance, "pctSigned"), {
      className: f.realised.return >= 0 ? "up" : "down",
    }));

    const pit = document.createElement("td");
    pit.append(renderFigure(figure(f.pit, provenance, "ratio3")));

    const hit = document.createElement("td");
    hit.append(chromeText(f.inside_80 ? "yes" : "no", "band hit, not a figure"));

    tr.append(d, spot, band, real, pit, hit);
    tbody.append(tr);
  }
  table.append(tbody);
  host.append(table);

  const why = document.createElement("p");
  why.className = "why";
  why.style.marginTop = "var(--sp-3)";
  why.style.color = "var(--ink-3)";
  why.style.fontSize = "var(--step--1)";
  why.append(chromeText(
    `${rows.length} scored forecast${rows.length === 1 ? "" : "s"} for this company. ` +
    `No coverage rate is shown: a rate needs about ${MIN_N_FOR_A_RATE} observations before ` +
    `it can tell a calibrated forecaster from a badly miscalibrated one. ` +
    `The measured rate is reported corpus-wide instead.`,
    "explanatory prose containing counts"));
  host.append(why);
}
