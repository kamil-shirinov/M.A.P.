/* The forecast cone, computed from the scenario mixture rather than stored.
   Two consequences: the band can never disagree with the scenario cards below
   it, and it is deterministic — no Monte Carlo, no seed to record. */

const SESSIONS_PER_YEAR = 252;

function erf(x) {
  const s = Math.sign(x); x = Math.abs(x);
  const t = 1 / (1 + 0.3275911 * x);
  const y = 1 - ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t
    - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x);
  return s * y;
}
const normalCdf = (x, mu, sd) => 0.5 * (1 + erf((x - mu) / (sd * Math.SQRT2)));

/** Scenario parameters at session t of a horizon of `horizon` sessions. */
function paramsAt(scenario, t, horizon) {
  return {
    w: scenario.probability_weight,
    mu: scenario.price_return * (t / horizon),
    sd: Math.max(scenario.annualised_vol * Math.sqrt(t / SESSIONS_PER_YEAR), 1e-6),
  };
}

function mixtureQuantile(parts, p) {
  let lo = -0.9, hi = 4.0;
  for (let i = 0; i < 60; i++) {
    const mid = (lo + hi) / 2;
    const cdf = parts.reduce((acc, q) => acc + q.w * normalCdf(mid, q.mu, q.sd), 0);
    if (cdf < p) lo = mid; else hi = mid;
  }
  return (lo + hi) / 2;
}

/** Quantile bands for sessions 1..horizon, as multiplicative returns on spot.
    Session 0 is the last close with zero width, which is what attaches the cone
    to real history rather than letting it float. */
export function coneBands(scenarios, spot, horizon, levels = [0.1, 0.25, 0.5, 0.75, 0.9]) {
  const list = Object.values(scenarios);
  const steps = [{ t: 0, prices: Object.fromEntries(levels.map((l) => [l, spot])) }];
  for (let t = 1; t <= horizon; t++) {
    const parts = list.map((s) => paramsAt(s, t, horizon));
    const prices = {};
    for (const l of levels) prices[l] = spot * (1 + mixtureQuantile(parts, l));
    steps.push({ t, prices });
  }
  return steps;
}

/** Extrapolate 5-session scenarios to another horizon. Return scales linearly,
    volatility by root-time. Uncalibrated by construction — see calibration.js. */
export function rescaleScenarios(scenarios, fromHorizon, toHorizon) {
  const k = toHorizon / fromHorizon;
  const out = {};
  for (const [name, s] of Object.entries(scenarios)) {
    out[name] = { ...s, price_return: s.price_return * k };
  }
  return out;
}
