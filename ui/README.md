# M.A.P. — front end

Static HTML, CSS and vanilla ES modules. No framework, no build step, no bundler.

## Running it

ES module imports are blocked over `file://`, so it needs to be served:

    cd ~/Desktop/map-ui
    python3 -m http.server 8756

Then open <http://127.0.0.1:8756/>. This is what `map ui` will do in production.

## Tests

    node --test

No runner, no `package.json`, no build step — Node's own test runner over
`tests/*.test.mjs`. Adding a framework here would contradict the line above.

## Generating the export

The front end reads a static export produced by the M.A.P. CLI. It is **not in this
repository** — `assets/export/` is gitignored, because it is 5.2 MB of generated JSON
whose contents change every time the corpus is re-scored.

    cd ~/Desktop/M.A.P.
    uv run map export --out ~/Desktop/map-ui/assets/export

Then serve this folder as below. `map export` refuses rather than writing a
half-export, naming the first input it could not read:

    error: the corpus ledger is missing at var/corpus/ledger.jsonl
      Run `map corpus run`, or pass --allow-partial to export without it.

A clone of M.A.P. has none of the generated inputs — no ledger, no symbol index, no
prices, no scores — so `--allow-partial` is what a newcomer gets: about 0.09 MB, the
frozen corpus and nothing else, with five absences named in the manifest. That is a
legitimate state and the interface has to render it.

To check an export has not gone stale behind the repository it came from:

    uv run map export --out ~/Desktop/map-ui/assets/export --check

It re-derives the identity of all seven inputs and names what moved. It writes nothing.

**`docs/export-contract.md` in the M.A.P. repository is the field-by-field contract** —
every file, its size, what each field claims, and the readings that are easy to get
wrong. Read it before wiring anything to these files.

## Structure

    index.html
    assets/styles/    tokens.css → base.css → components.css
    assets/js/
      main.js           composition root; owns app state
      data/source.js    THE data boundary — fixtures now, fetch() later
      data/fixtures/    universe, market series, corpus reliability
      lib/              figure, provenance-audit, calibration, cone, format
      ui/               search, chart, scenarios, horizon, track-record,
                        reliability, audit-strip

## The three rules the code enforces

**1. One data boundary.** Nothing outside `data/source.js` knows where data comes
from. Every function is async today even though fixtures resolve instantly — if
they were synchronous, every call site would change the day this starts reading
`runs/` over HTTP.

**2. Provenance travels with every number.** `measured` (read from an artifact),
`derived` (computed here from measured inputs), `fabricated` (from a fixture, or
derived from anything fabricated). Weakest input wins, so provenance cannot be
laundered through arithmetic. `source.js` stamps it; fixture files do not
describe themselves.

Every text node containing a digit must sit inside `[data-prov]` (a figure) or
`[data-chrome]` (positively marked as not a figure). `lib/provenance-audit.js`
has **no heuristics** — "skip things shaped like a date" is how a real value
formatted as `2026.07` passes unnoticed. Forgetting to mark something outlines
it in the page and throws in the console on the next paint.

Page-level: if any figure on the page is fabricated, the banner *and* the chart
watermark both show. Per-figure marking handles the figure; the page needs its
own state, because the realistic crop is one region, not the whole page.

#### Why the audit has no heuristics — the case that proves it

`data/source.js` states the rule in its own header: *sentence builders return
parts, never prose with a figure welded in.* It then shipped this:

```js
text(` on ${o.trading_date}, retrieved ${o.retrieved_on} from the ${o.snapshot} snapshot.`)
```

A correctly marked price, followed by three unmarked dates in one interpolated
string. The module that states the rule broke it.

The unit test for that rule passed. It asserted `/\d+\.\d{2,}/` — decimals — so
it caught a welded price and never saw a date. A test written to catch the
failure you imagined is blind to the one you did not.

What caught it was the page-level audit, walking the rendered tree and flagging
every text node with a digit that sits outside `[data-prov]` or `[data-chrome]`.
It has no idea what a date is, which is exactly why it saw one.

**The order matters.** A heuristic audit — "skip things shaped like a date" —
would have skipped these three and stayed silent. The narrow test and the
heuristic audit would have failed together, for the same reason: both encode a
guess about which numbers are interesting. The audit's ignorance is its value.

Sentence builders now return a third part kind, `{kind: "chrome", text, why}`, so
a date arrives as a marked node instead of as string interpolation. The unit test
now asserts *no digit at all* in a text part.

**3. Calibration is one attribute.** `lib/calibration.js` owns
`CALIBRATED_HORIZONS = [5]` and nothing else decides. Every visual difference
hangs off `[data-calibration]` on the forecast root, so half of it cannot be
styled by accident. Uncalibrated horizons are not separate forecasts — they are
the five-session scenarios extrapolated, and the interface says so.

## Deliberate decisions worth reversing if you disagree

- **The forecast region takes a fixed 26% of the chart width** regardless of
  horizon. At one pixel per session a five-session cone is 4% of the chart —
  invisible, and it is the entire product. The cost is a broken x-scale at the
  join, so the break is drawn as a dashed rule and labelled.
- **The cone is computed, not stored.** `lib/cone.js` inverts the weighted
  scenario mixture numerically, so the band can never disagree with the cards
  below it, and there is no seed to record.
- **No per-ticker coverage rate.** Two or three filings a company; a rate on
  n=3 spans most of the unit line. `MIN_N_FOR_A_RATE = 80` gives 80% power to
  detect a 20-point departure from stated coverage — and no ticker can reach it,
  which is why the element does not exist rather than sitting permanently in a
  degraded state.
- **PIT leads, band-hit follows.** A column of yes/no invites the reader to
  count them and form "2 of 3" by eye — the statistic we decline to print.

## Not done

- Design language is placeholder. `map-ui-prototype.html` never arrived; when it
  does, `tokens.css` and `components.css` are where it lands.
- Trace link is a stub anchor.
- Universe is 84 real listings padded to 9,800 generated ones, flagged
  `synthetic` and surfaced as "invented listing" in the header.
