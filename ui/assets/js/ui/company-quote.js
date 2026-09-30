/* The market now, at the top of a company page — in the local app only (ADR 0039).

   The latest trade, New York's clock, and whether the market is open, with where
   the quote comes from and that it may be delayed said beside the price. Asked of
   the local server, which asks Yahoo through this machine. The hosted copy has
   no server and shows nothing here: Yahoo's data is not ours to republish.

   ASKED AGAIN WHEN THE SERVER SAYS: about once a minute while the market is
   open, and at the next opening bell while it is shut. The server knows New
   York's hours, so this module does not. New York's clock beside the price is
   read from this machine and moves on its own minute; the time of the trade is
   said separately, because the two are not the same minute and a delayed quote
   is exactly the case where they differ.

   A QUOTE IS NOT A CLOSE. Nothing in the record reads it: the chart below draws
   closes, and every run's figures come from the pinned snapshot. */

import { chromeText, renderFigure } from "../lib/figure.js";
import { isAbsent } from "../data/source.js";

const NY = "America/New_York";
// Never sooner than this, whatever a server says: a page must not hammer it.
const MIN_WAIT_S = 30;
// A quote that could not be had is asked for again after this long.
const RETRY_S = 300;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "14:32" on New York's clock, and "Tue 29 Sep" when the day is asked for. */
export function newYork(instant, { day = false } = {}) {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-US", {
      timeZone: NY, weekday: "short", year: "numeric", month: "numeric", day: "numeric",
      hour: "2-digit", minute: "2-digit", hourCycle: "h23",
    }).formatToParts(instant).map((p) => [p.type, p.value]),
  );
  const time = `${parts.hour}:${parts.minute}`;
  if (!day) return time;
  return `${time}, ${parts.weekday} ${Number(parts.day)} ${MONTHS[Number(parts.month) - 1]}`;
}

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

/** Mount the quote into `root` and keep it current. Returns `stop()`. */
export function mountQuote(root, { ticker, fetchQuote, now = () => new Date(), wait = setTimeout, cancel = clearTimeout }) {
  let asking = null;
  let ticking = null;
  let stopped = false;
  let quote = null;

  const paint = () => {
    root.textContent = "";
    if (!quote) return;
    if (isAbsent(quote)) {
      const p = el("p", "cmp-quote-none");
      p.append(chromeText(`No live quote: ${quote.why}.`, "why there is no quote"));
      root.append(p);
      return;
    }
    const open = quote.market === "open";
    const line = el("p", "cmp-quote-line");
    // The page's title already names the company; the line starts with its price.
    line.append(
      renderFigure(quote.price),
      el("span", "cmp-quote-state", open ? "market open" : "market closed"),
      chromeText(`New York ${newYork(now())}`, "the time in New York now"),
    );
    line.dataset.market = quote.market;
    const source = el("p", "cmp-quote-source");
    const traded = new Date(quote.at);
    source.append(chromeText(
      `${open ? "Last trade" : "Last trade before the close"} ${newYork(traded, { day: !open })} New York, ` +
        `from Yahoo Finance via ${quote.provider}, and it may be delayed. ` +
        (open ? "Asked again about once a minute while the market is open." : "Asked again at the next opening bell."),
      "where the quote comes from, when it traded, and how often it is asked for",
    ));
    root.append(line, source);
  };

  const ask = async () => {
    asking = null;
    const answer = await fetchQuote(ticker);
    if (stopped) return;
    quote = answer;
    paint();
    const seconds = isAbsent(answer) ? RETRY_S : Math.max(MIN_WAIT_S, Number(answer.next_check_s) || RETRY_S);
    asking = wait(ask, seconds * 1000);
    asking?.unref?.();
  };

  // New York's clock moves on its own minute between quotes, read off this machine.
  const tick = () => {
    paint();
    ticking = wait(tick, 60_000 - (now().getTime() % 60_000));
    ticking?.unref?.();
  };

  ask();
  ticking = wait(tick, 60_000 - (now().getTime() % 60_000));
  ticking?.unref?.();

  return {
    stop() {
      stopped = true;
      if (asking !== null) cancel(asking);
      if (ticking !== null) cancel(ticking);
    },
  };
}
