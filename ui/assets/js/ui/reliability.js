import { figure, renderFigure, chromeText } from "../lib/figure.js";

/* Corpus-wide only. Refuses to render if handed anything else, so the
   separation from the per-ticker table is enforced by the data rather than by
   remembering where the element was placed. */

export function renderReliability(host, r) {
  host.textContent = "";
  if (r.scope !== "corpus") {
    const p = document.createElement("p");
    p.className = "empty";
    p.textContent = "Reliability is reported corpus-wide only.";
    host.append(p);
    return;
  }

  const wrap = document.createElement("div");
  wrap.className = "reliability";

  const scope = document.createElement("p");
  scope.className = "scope";
  scope.append(chromeText(
    `Measured across the whole corpus — ${r.n} scored forecasts over ${r.date_clusters} ` +
    `date clusters, ${r.band} band, ${r.split} split, ${r.horizon_days}-session horizon. ` +
    `Not a property of any one company.`, "scope prose with counts"));
  wrap.append(scope);

  const row = (k, node) => {
    const d = document.createElement("div");
    d.className = "row";
    const kk = document.createElement("span");
    kk.className = "k";
    kk.append(typeof k === "string" ? document.createTextNode(k) : k);
    const vv = document.createElement("span");
    vv.className = "v";
    vv.append(node);
    d.append(kk, vv);
    wrap.append(d);
  };

  row(chromeText("Stated coverage of the 10–90% band", "band label with percents"),
    renderFigure(figure(r.stated_coverage, r.provenance, "pct")));
  row("Measured coverage", renderFigure(figure(r.measured_coverage, r.provenance, "pct")));

  const iv = document.createElement("span");
  iv.append(renderFigure(figure(r.interval.low, r.provenance, "pct")));
  iv.append(chromeText(" to ", "range separator"));
  iv.append(renderFigure(figure(r.interval.high, r.provenance, "pct")));
  row(chromeText("95% interval", "confidence level in a label"), iv);

  const method = document.createElement("p");
  method.className = "scope";
  method.append(chromeText(
    `${r.interval.method}. ${r.note}`, "method prose containing a block length"));
  wrap.append(method);

  host.append(wrap);
}
