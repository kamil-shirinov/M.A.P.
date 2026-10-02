/* Fabricated market data, generated deterministically from the ticker symbol so
   every listing is viewable and the same symbol always yields the same series.

   Magnitudes are realistic because layout has to be testable at real scale.
   Values are NOT taken from any actual result: reusing a real measured number
   inside a fabricated fixture would make the two indistinguishable if the
   marking were ever stripped, which is the failure this whole scheme exists to
   prevent. */

function seedFrom(text) {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) { h ^= text.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}
function lcg(seed) {
  let s = seed >>> 0;
  return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296);
}
function gauss(rand) {
  const u = Math.max(rand(), 1e-9), v = rand();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

const SESSIONS = 126;              // roughly six months of trading days
const LAST_SESSION = "2026-08-14"; // the pinned price vintage in the fixtures

function sessionDates(count, lastIso) {
  const out = [];
  const d = new Date(lastIso + "T00:00:00Z");
  while (out.length < count) {
    const day = d.getUTCDay();
    if (day !== 0 && day !== 6) out.push(d.toISOString().slice(0, 10));
    d.setUTCDate(d.getUTCDate() - 1);
  }
  return out.reverse();
}

export function historyFor(symbol) {
  const rand = lcg(seedFrom(symbol));
  const base = 12 + rand() * 280;
  const annualVol = 0.16 + rand() * 0.28;
  const drift = (rand() - 0.45) * 0.22;
  const daily = annualVol / Math.sqrt(252);
  const dates = sessionDates(SESSIONS, LAST_SESSION);

  let price = base;
  const sessions = dates.map((date) => {
    price *= 1 + drift / 252 + daily * gauss(rand);
    price = Math.max(price, 0.6);
    return [date, Math.round(price * 100) / 100];
  });
  return { ticker: symbol, currency: "USD", vintage: LAST_SESSION, sessions };
}

export function forecastFor(symbol, history) {
  const rand = lcg(seedFrom(symbol + "|forecast"));
  const spot = history.sessions.at(-1)[1];
  const closes = history.sessions.map((s) => s[1]);
  let sum = 0;
  for (let i = 1; i < closes.length; i++) {
    const r = Math.log(closes[i] / closes[i - 1]);
    sum += r * r;
  }
  const realisedVol = Math.sqrt((sum / (closes.length - 1)) * 252);

  // Rounded to three places and closed on the base case, so the three weights
  // sum to exactly 1 rather than to 0.999 — a visible sloppiness in a UI that
  // prints them as percentages.
  const wBull = Number((0.22 + rand() * 0.16).toFixed(3));
  const wBear = Number((0.20 + rand() * 0.16).toFixed(3));
  const wBase = Number((1 - wBull - wBear).toFixed(3));

  return {
    schema_version: "2.0.0",
    run_id: "f" + seedFrom(symbol).toString(16).padStart(8, "0") + "-4a1c-9e02-b7d3",
    ticker: symbol,
    as_of: "2026-08-15",
    filing_date: "2026-08-14",
    horizon_days: 5,
    spot_price: spot,
    scenarios: {
      bullish: {
        label: "Bullish",
        probability_weight: wBull,
        price_return: Number((0.014 + rand() * 0.026).toFixed(4)),
        annualised_vol: Number((realisedVol * (0.82 + rand() * 0.18)).toFixed(4)),
        justification:
          "Margin commentary points to pricing power holding through the quarter, with " +
          "guidance framed above the prior range.",
      },
      base_case: {
        label: "Base case",
        probability_weight: wBase,
        price_return: Number(((rand() - 0.5) * 0.012).toFixed(4)),
        annualised_vol: Number((realisedVol * (0.78 + rand() * 0.14)).toFixed(4)),
        justification:
          "Release reads in line with the trailing four quarters; no change to the " +
          "operating outlook and no revision to full-year guidance.",
      },
      bearish: {
        label: "Bearish",
        probability_weight: wBear,
        price_return: Number((-(0.013 + rand() * 0.025)).toFixed(4)),
        annualised_vol: Number((realisedVol * (0.9 + rand() * 0.22)).toFixed(4)),
        justification:
          "Input costs and a softer volume line could compress the margin if the " +
          "demand commentary proves optimistic.",
      },
    },
    models: [
      { role: "intake", name: "llama-3.2-3b-instruct", runtime_ms: 3600 + Math.round(rand() * 2200) },
      { role: "analyst", name: "google/gemma-4-12b-qat", runtime_ms: 24000 + Math.round(rand() * 26000) },
      { role: "structuralist", name: "qwen/qwen3-4b-2507", runtime_ms: 4200 + Math.round(rand() * 3800) },
    ],
    trace: { href: "#trace", events: 9 + Math.floor(rand() * 8) },
  };
}

/* Two or three past forecasts per ticker, matching the corpus: each company
   contributes a handful of filings, never a long personal history. */
export function trackRecordFor(symbol, history) {
  const rand = lcg(seedFrom(symbol + "|track"));
  const n = 2 + Math.floor(rand() * 2);
  const dates = ["2026-02-06", "2026-04-24", "2026-07-17"].slice(0, n);
  const closes = history.sessions;

  return {
    ticker: symbol,
    forecasts: dates.map((asOf, i) => {
      const at = closes[Math.min(20 + i * 34, closes.length - 6)];
      const after = closes[Math.min(25 + i * 34, closes.length - 1)];
      const spot = at[1];
      const realisedReturn = after[1] / spot - 1;
      const width = 0.035 + rand() * 0.03;
      const centre = (rand() - 0.5) * 0.01;
      const p10 = centre - width, p90 = centre + width;
      const pit = Math.min(0.995, Math.max(0.005,
        0.5 + (realisedReturn - centre) / (width * 2.5)));
      return {
        as_of: asOf,
        horizon_days: 5,
        run_id: "f" + seedFrom(symbol + asOf).toString(16).padStart(8, "0"),
        spot_price: spot,
        stated: { p10, p50: centre, p90 },
        realised: { close: after[1], return: realisedReturn },
        pit: Number(pit.toFixed(3)),
        inside_80: realisedReturn >= p10 && realisedReturn <= p90,
        was_calibrated: true,
      };
    }),
  };
}
