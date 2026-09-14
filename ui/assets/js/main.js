import * as source from "./data/source.js";
import { mountSearch } from "./ui/search.js";
import { renderChart } from "./ui/chart.js";
import { renderScenarios } from "./ui/scenarios.js";
import { renderHorizon } from "./ui/horizon.js";
import { renderTrackRecord } from "./ui/track-record.js";
import { renderReliability } from "./ui/reliability.js";
import { renderAudit } from "./ui/audit-strip.js";
import { calibrationState } from "./lib/calibration.js";
import { rescaleScenarios } from "./lib/cone.js";
import { enforce, applyPageProvenance } from "./lib/provenance-audit.js";
import { chromeText } from "./lib/figure.js";

const $ = (id) => document.getElementById(id);

const state = { ticker: "AAPL", listing: null, horizon: 5, universe: [] };

async function paint() {
  const [history, forecast, record, reliability] = await Promise.all([
    source.getHistory(state.ticker),
    source.getForecast(state.ticker),
    source.getTrackRecord(state.ticker),
    source.getCorpusReliability(),
  ]);

  const root = $("forecast-root");
  // One attribute drives every visual difference between a calibrated and an
  // uncalibrated forecast, so half of it cannot be styled by accident.
  root.dataset.calibration = calibrationState(state.horizon);

  const scenarios = state.horizon === forecast.horizon_days
    ? forecast.scenarios
    : rescaleScenarios(forecast.scenarios, forecast.horizon_days, state.horizon);

  $("ticker-name").textContent = state.ticker;
  const meta = $("ticker-meta");
  meta.textContent = "";
  const listing = state.listing || state.universe.find((r) => r.symbol === state.ticker);
  if (listing) {
    meta.append(document.createTextNode(listing.name + " · " + listing.exchange));
    if (listing.synthetic) {
      const s = document.createElement("span");
      s.style.color = "var(--fab)";
      s.textContent = " · invented listing";
      meta.append(s);
    }
  }

  $("vintage").textContent = "";
  $("vintage").append(chromeText("prices as of " + history.vintage, "price vintage date"));

  renderChart($("chart"), { history, forecast, horizon: state.horizon, scenarios });
  renderHorizon($("horizon"), { horizon: state.horizon, onChange: (h) => { state.horizon = h; paint(); } });
  renderScenarios($("scenarios"), {
    scenarios, spot: forecast.spot_price, provenance: forecast.provenance,
  });
  renderTrackRecord($("track-record"), { record, provenance: record.provenance });
  renderReliability($("reliability"), reliability);
  renderAudit($("audit"), {
    models: forecast.models, trace: forecast.trace,
    runId: forecast.run_id, provenance: forecast.provenance,
  });

  applyPageProvenance();
  enforce();
}

async function boot() {
  const { rows } = await source.listUniverse();
  state.universe = rows;
  mountSearch($("search"), {
    universe: rows,
    initial: state.ticker,
    onSelect: (row) => { state.ticker = row.symbol; state.listing = row; paint(); },
  });
  await paint();
}

boot();
