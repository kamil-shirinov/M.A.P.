# M.A.P. — front end

Static HTML, CSS and vanilla ES modules. No framework, no build step, no bundler.

## Running it

ES module imports are blocked over `file://`, so it needs to be served:

    cd ~/Desktop/map-ui
    python3 -m http.server 8756

Then open <http://127.0.0.1:8756/>. This is what `map ui` will do in production.

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
