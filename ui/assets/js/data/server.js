/* The local server, when there is one. Every request a page makes to it is here.

   `source.js` reads the export: files, written once, the same on every copy. This
   module reads what only a running `map serve` can answer — a price window for a
   company the export never read, the live runs made since the last export — and
   starts the one request that makes anything exist.

   Kept apart from `source.js` because the two answer to different things. An
   export is a record and cannot change under a page; a server answers about this
   machine, now, and is absent on every published copy. A function here that is
   called on a copy with no server must answer with an absence, never throw. */

import { MEASURED, figure } from "../lib/figure.js";
import { NOT_COMPUTED, absent, adaptRunRow } from "./source.js";

let probe = null;

/** Is a server behind these files? One GET, once per page load.

    `health` rather than a speculative POST: asking the question must never be
    able to start a run, because a run costs minutes and is permanent. */
export function serverPresent() {
  probe ??= fetch("health", { method: "GET" })
    .then((response) => response.ok)
    .catch(() => false);
  return probe;
}

/** For tests: forget the memoised answer. */
export function resetProbe() {
  probe = null;
}

async function refusal(response) {
  const body = await response.json().catch(() => ({}));
  return body.why ?? `the server answered ${response.status}`;
}

/** A company's price history, fetched through this machine's price cache.

    Returned in the shape `getPriceSeries` gives for an exported series, with one
    difference that is printed rather than hidden: `fetched_on` in place of a
    pinned snapshot. The export's series is a vintage anyone can re-read; this is
    whatever the provider said today, stored under today's date. */
export async function fetchPrices(ticker) {
  if (!(await serverPresent())) {
    return absent(NOT_COMPUTED, "no server is behind these files to fetch a series");
  }
  let response;
  try {
    response = await fetch(`prices?ticker=${encodeURIComponent(ticker)}`);
  } catch {
    return absent(NOT_COMPUTED, "the server did not answer the price request");
  }
  if (!response.ok) return absent(NOT_COMPUTED, await refusal(response));
  const body = await response.json();
  const last = body.bars.at(-1);
  return {
    ticker: body.ticker,
    sessions: body.bars,
    provider: body.provider,
    adjustment: body.adjustment,
    fetched_on: body.fetched_on,
    served: true,
    last_close: figure(last[1], MEASURED, "price"),
    last_close_date: last[0],
    provenance: MEASURED,
  };
}

/** This company's live runs from the journal the server writes to, newest first.

    `null` when there is no server or it could not answer, so the caller falls
    back to the export's rows — which are the same shape, one export older. */
export async function fetchLiveRuns(ticker) {
  if (!(await serverPresent())) return null;
  try {
    const response = await fetch(`runs?ticker=${encodeURIComponent(ticker)}`);
    if (!response.ok) return null;
    return (await response.json()).map(adaptRunRow);
  } catch {
    return null;
  }
}

/** Start an analysis and hand each streamed line to `onEvent` as it arrives.

    Newline-delimited JSON, read as it comes: buffering it would turn a progress
    display into a blank lasting the length of the run. Resolves when the stream
    ends; a refusal or a dropped connection arrives as one `failed` event, so the
    caller has a single place to say why a run stopped. */
export async function streamAnalysis(ticker, horizon, onEvent) {
  let response;
  try {
    response = await fetch("analyse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ticker, horizon_days: horizon }),
    });
  } catch (error) {
    onEvent({ event: "failed", why: `the server did not answer: ${error.message ?? error}` });
    return;
  }
  if (!response.ok) {
    onEvent({ event: "failed", why: await refusal(response) });
    return;
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n");
      buffer = parts.pop() ?? "";
      for (const part of parts) if (part.trim()) onEvent(JSON.parse(part));
    }
    if (buffer.trim()) onEvent(JSON.parse(buffer));
  } catch (error) {
    onEvent({ event: "failed", why: `the stream broke off: ${error.message ?? error}` });
  }
}
