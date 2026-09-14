/* THE data boundary. Nothing else in the app knows where data comes from.

   Every function is async today even though fixtures resolve instantly. If they
   were synchronous, every call site would have to change the day this starts
   reading runs/ over HTTP — which is the whole reason the module exists.

   This module also STAMPS provenance. Fixture files do not declare their own,
   because a file that describes itself can be wrong; the boundary tags whatever
   it hands out. When `map ui` starts serving real artifacts, the stamp here
   becomes MEASURED for those reads and nothing upstream changes. */

import { UNIVERSE } from "./fixtures/universe.js";
import { historyFor, forecastFor, trackRecordFor } from "./fixtures/market.js";
import { CORPUS_RELIABILITY } from "./fixtures/reliability.js";
import { FABRICATED } from "../lib/figure.js";

const SOURCE = FABRICATED; // flip per-read when runs/ is wired

const settle = (value) => Promise.resolve(value);

export async function listUniverse() {
  return settle({ rows: UNIVERSE, provenance: SOURCE });
}

export async function getHistory(ticker) {
  return settle({ ...historyFor(ticker), provenance: SOURCE });
}

export async function getForecast(ticker) {
  const history = historyFor(ticker);
  return settle({ ...forecastFor(ticker, history), provenance: SOURCE });
}

export async function getTrackRecord(ticker) {
  const history = historyFor(ticker);
  return settle({ ...trackRecordFor(ticker, history), provenance: SOURCE });
}

export async function getCorpusReliability() {
  return settle({ ...CORPUS_RELIABILITY, provenance: SOURCE });
}
