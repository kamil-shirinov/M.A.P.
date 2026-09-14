import { coneBands } from "../lib/cone.js";

const NS = "http://www.w3.org/2000/svg";
const W = 900, H = 340;
const PAD = { t: 16, r: 66, b: 34, l: 12 };

/* The forecast region gets a fixed share of the plot width regardless of how
   many sessions it covers. At one pixel per session a five-session cone is 4%
   of the chart — invisible, and it is the entire product. The cost is that the
   x-scale breaks at the join, so the break is drawn and labelled rather than
   left for the eye to miss. */
const FORECAST_SHARE = 0.26;

const MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

const el = (name, attrs = {}) => {
  const node = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
};

/* Axis text contains digits and is not a figure, so it is positively marked as
   chrome. The audit is given no heuristics to guess with. */
const label = (x, y, text, anchor = "end", cls = "") => {
  const t = el("text", { x, y, "text-anchor": anchor });
  if (cls) t.setAttribute("class", cls);
  t.dataset.chrome = "chart axis tick";
  t.textContent = text;
  return t;
};

const monthLabel = (iso) => `${MONTHS[+iso.slice(5, 7) - 1]} ${iso.slice(0, 4)}`;
const dayLabel = (iso) => `${+iso.slice(8, 10)} ${MONTHS[+iso.slice(5, 7) - 1]}`;

export function renderChart(host, { history, horizon, scenarios }) {
  host.textContent = "";

  const closes = history.sessions.map((s) => s[1]);
  const dates = history.sessions.map((s) => s[0]);
  const spot = closes.at(-1);
  const bands = coneBands(scenarios, spot, horizon);

  const nHist = closes.length;
  const lows = bands.map((b) => b.prices[0.1]);
  const highs = bands.map((b) => b.prices[0.9]);
  const min = Math.min(...closes, ...lows);
  const max = Math.max(...closes, ...highs);
  const pad = (max - min) * 0.08 || 1;
  const yMin = min - pad, yMax = max + pad;

  const plotW = W - PAD.l - PAD.r;
  const plotH = H - PAD.t - PAD.b;
  const foreW = plotW * FORECAST_SHARE;
  const histW = plotW - foreW;
  const joinX = PAD.l + histW;

  const xh = (i) => PAD.l + (i / (nHist - 1)) * histW;
  const xf = (t) => joinX + (t / horizon) * foreW;
  const y = (v) => PAD.t + (1 - (v - yMin) / (yMax - yMin)) * plotH;

  const svg = el("svg", {
    class: "chart", viewBox: `0 0 ${W} ${H}`, role: "img",
    "aria-label": `Six months of closes for ${history.ticker} with a ${horizon}-session forecast band`,
  });

  const grid = el("g", { class: "grid" });
  const axis = el("g", { class: "axis" });
  for (let i = 0; i <= 5; i++) {
    const v = yMin + (i / 5) * (yMax - yMin);
    grid.appendChild(el("line", { x1: PAD.l, x2: PAD.l + plotW, y1: y(v), y2: y(v) }));
    axis.appendChild(label(W - 10, y(v) + 4, v.toFixed(2)));
  }
  svg.append(grid);

  axis.appendChild(label(xh(0), H - 10, monthLabel(dates[0]), "start"));
  axis.appendChild(label(xh(Math.floor(nHist / 2)), H - 10, monthLabel(dates[Math.floor(nHist / 2)]), "middle"));
  axis.appendChild(label(joinX, H - 10, dayLabel(dates.at(-1)), "middle"));
  axis.appendChild(label(joinX + foreW / 2, H - 10,
    `${horizon} session${horizon === 1 ? "" : "s"} ahead`, "middle", "forecast-region"));
  svg.append(axis);

  // The cone attaches at the last close: session 0 of the band IS that point.
  const area = (loKey, hiKey) => {
    const up = bands.map((b) => `${xf(b.t)},${y(b.prices[loKey])}`);
    const down = bands.slice().reverse().map((b) => `${xf(b.t)},${y(b.prices[hiKey])}`);
    return [...up, ...down].join(" ");
  };
  svg.append(el("polygon", { class: "cone-80", points: area(0.1, 0.9) }));
  svg.append(el("polygon", { class: "cone-50", points: area(0.25, 0.75) }));
  svg.append(el("polyline", {
    class: "cone-median",
    points: bands.map((b) => `${xf(b.t)},${y(b.prices[0.5])}`).join(" "),
  }));

  // The scale break, drawn because it is real.
  svg.append(el("line", { class: "join", x1: joinX, x2: joinX, y1: PAD.t, y2: PAD.t + plotH }));

  svg.append(el("polyline", {
    class: "price-line",
    points: closes.map((c, i) => `${xh(i)},${y(c)}`).join(" "),
  }));
  svg.append(el("circle", { class: "spot-dot", cx: joinX, cy: y(spot), r: 2.5 }));

  host.append(svg);
  return svg;
}
