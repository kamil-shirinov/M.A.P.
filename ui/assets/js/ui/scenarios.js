import { figure, derive, renderFigure, chromeText } from "../lib/figure.js";

const ORDER = ["bullish", "base_case", "bearish"];

export function renderScenarios(host, { scenarios, spot, provenance }) {
  host.textContent = "";
  for (const key of ORDER) {
    const s = scenarios[key];
    if (!s) continue;

    const card = document.createElement("article");
    card.className = "scenario";

    const h = document.createElement("h3");
    h.textContent = s.label || key.replace("_", " ");
    card.append(h);

    const ret = figure(s.price_return, provenance, "pctSigned");
    const vol = figure(s.annualised_vol, provenance, "pct");
    const w = figure(s.probability_weight, provenance, "weight");
    const target = derive(spot * (1 + s.price_return), "price",
      figure(spot, provenance), ret);

    const t = document.createElement("div");
    t.className = "target";
    t.append(renderFigure(target, { className: "lg " + (s.price_return >= 0 ? "up" : "down") }));
    card.append(t);

    const dl = document.createElement("dl");
    const put = (k, node) => {
      const dt = document.createElement("dt"); dt.textContent = k;
      const dd = document.createElement("dd"); dd.append(node);
      dl.append(dt, dd);
    };
    put("Return", renderFigure(ret, { className: s.price_return >= 0 ? "up" : "down" }));
    put("Volatility", renderFigure(vol));
    put("Weight", renderFigure(w));
    card.append(dl);

    const bar = document.createElement("div");
    bar.className = "weightbar";
    const fill = document.createElement("i");
    fill.style.width = (s.probability_weight * 100).toFixed(1) + "%";
    bar.append(fill);
    card.append(bar);

    const why = document.createElement("p");
    why.className = "why";
    why.textContent = s.justification;
    card.append(why);

    host.append(card);
  }
}
