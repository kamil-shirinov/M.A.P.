"""The per-item scoring pass: forecast plus outcome plus baselines, into scores.

This is where the pieces meet. For each completed item it reads the stored
forecast, finds what actually happened, fits the three baselines on history
strictly before the window opened, and scores all four forecasters on the same
realised return.

Four decisions that are not obvious.

**M.A.P. is scored through the Monte Carlo mixture, the baselines in closed form.**
Fitting a Gaussian to the mixture and scoring that would discard the bimodality
that is the whole reason the mixture exists; the baselines genuinely are Gaussian,
so the closed form is exact rather than an approximation of them.

**The realised return is measured from the forecast's own recorded spot**, not from
whatever the price source returns today. The two should agree, and when they do not
the corpus is being scored against a different price series than the one it was
produced from — a vintage drift that ADR 0012 exists to make impossible and this
checks anyway, because "impossible" is a claim about code that can change.

**An unclosed window is refused, not skipped.** A forecast whose horizon has not
elapsed cannot be scored, and quietly dropping it would shrink the reportable
sample without saying so.

**Everything is parameterised by Protocols.** `mapf.eval` may not import
`mapf.data`, and that is what keeps this testable with generated series rather than
a live price feed.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np

from mapf.core.errors import MapError
from mapf.core.models import ADJUSTMENT_BASIS, Bar, Forecast, PriceWindow
from mapf.eval.baselines import (
    BaselineError,
    History,
    Prediction,
    earnings_multiplier,
    earnings_scaled_random_walk,
    garch,
    random_walk,
)
from mapf.eval.montecarlo import DEFAULT_PATHS, crps_against, simulate
from mapf.eval.scoring import brier, crps_normal, log_score_normal, pit

# Prices should match the forecast's recorded spot to the cent. A tolerance this
# loose only catches genuine drift — a different adjustment basis or vintage —
# rather than float noise.
SPOT_TOLERANCE = 1e-4

EPOCH = date(2000, 1, 1)


class ScoringError(MapError):
    """An item could not be scored."""


class WindowNotClosedError(ScoringError):
    """The forecast horizon has not elapsed yet.

    Refused rather than skipped: silently dropping unfinished windows would shrink
    the reportable sample without anything saying so.
    """


class SpotDriftError(ScoringError):
    """The price series disagrees with the spot the forecast was produced from.

    Means the corpus is being scored against different prices than it was run on —
    a retroactive adjustment or a mixed vintage (ADR 0012).
    """


class RealisedDriftError(ScoringError):
    """The outcome bar disagrees with the one this item was first scored against.

    `SpotDriftError` anchors the numerator of the return; this anchors the
    denominator's counterpart — the realised close — and nothing else does. The
    asymmetry is not an oversight in the original design: the spot can be pinned at
    forecast time because the forecast records it, while the outcome does not exist
    yet and structurally cannot be recorded then. So the pin is taken at FIRST
    SCORING and enforced on every later one.

    Phase 3 is why it exists. The correction is fitted on the development half and
    then tested once on the holdout, both scored after the numbers already reported.
    A realised bar that drifts in between would have the correction fitted against
    outcomes different from the ones published, with nothing to say so.

    Date and close are both compared: a shifted bar that happens to close nearby
    would slip a value-only check, and the shift is the more dangerous error because
    it silently re-times the horizon.
    """


class VintageError(ScoringError):
    """Two prices in one comparison do not share an adjustment basis or a source.

    A realised return is a ratio of two prices, and a ratio is only meaningful when
    both sides are on the same basis. Within one item that holds by construction —
    both endpoints are bars of a single `PriceWindow`, which carries one provider
    and one adjustment for the whole series — so this asserts what construction
    already provides, because "by construction" is a claim about code that changes.

    Across a band it does *not* hold by construction, and that is the reachable
    failure: the provider chain fails over per call, so one ticker can be served by
    yfinance and the next by stooq, and the price cache is keyed by `fetched_on`,
    so a scoring pass spanning midnight mixes two vintages. Both produce well-formed
    windows that silently mean different things.
    """


class LookAheadError(ScoringError):
    """A baseline was handed an event dated at or after the forecast opens.

    The earnings multiplier is the likeliest place for look-ahead to re-enter,
    because "the ticker's earnings dates" reads as a static property of the ticker
    rather than as a point-in-time question. Raised rather than filtered: dropping
    the offending dates silently would leave a broken adapter looking correct.
    """


@dataclass(frozen=True)
class RealisedPin:
    """The outcome bar an item was first scored against."""

    ticker: str
    as_of: date
    horizon_days: int
    realised_date: date
    realised_close: float

    @property
    def key(self) -> tuple[str, date, int]:
        return (self.ticker, self.as_of, self.horizon_days)


# Injected rather than imported, so this module still never reaches `mapf.data`.
PinReader = Callable[[str, date, int], RealisedPin | None]
PinWriter = Callable[[RealisedPin], None]


@dataclass(frozen=True)
class ScoredItem:
    """One forecast, its outcome, and every forecaster's score on it."""

    ticker: str
    band: str
    as_of: date
    horizon_days: int
    realised_return: float
    day_index: int
    map_crps: float
    map_sigma: float
    map_pit: float
    # The log score and Brier are taken on a NORMAL fitted to the simulation's mean
    # and sigma, not on the ensemble itself. A density estimate over the paths would
    # need a bandwidth, and a bandwidth is a free parameter chosen after seeing the
    # outcome unless it is pre-registered. `map_pit` already uses the same normal, so
    # the three agree about what distribution is being scored.
    map_log_score: float
    # Brier is the exception, and deliberately: P(up) is read straight off the
    # ensemble, because a directional probability is exactly what the paths answer
    # without any smoothing at all.
    map_brier: float
    # Kept so the directional claim can be reported as an accuracy, not only as a
    # squared error. A Brier of 0.25 is what a coin flip scores AND what a confident
    # forecaster scores when it is wrong exactly half the time; the two are only
    # distinguishable if the probabilities themselves are available.
    map_probability_up: float
    baseline_crps: dict[str, float]
    baseline_log_score: dict[str, float]
    baseline_brier: dict[str, float]
    # The series this item was scored against. Carried per item so `score_band` can
    # refuse a band whose items were priced from different sources — the reachable
    # half of the vintage problem (ADR 0023).
    provider: str = ""
    adjustment: str = ADJUSTMENT_BASIS
    # What the earnings baseline actually widened by. Recorded because a multiplier
    # pinned at 1.0 is a benchmark that declines to widen for a scheduled event —
    # easy to beat, and easy for a reason invisible in the score (ADR 0023). `None`
    # means the baseline could not be fitted at all.
    earnings_multiplier: float | None = None

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self.baseline_crps))


def realised_return(window: PriceWindow, as_of: date, horizon_days: int, spot: float) -> float:
    """Log return over the horizon, anchored on the forecast's own spot.

    `as_of` is the last trading date the forecast saw. The horizon is counted in
    trading days, so it is an index offset in the bar series rather than a calendar
    delta — a five-day window over a long weekend is still five bars.

    **Both endpoints come from one window, and that is asserted rather than
    assumed.** The numerator and denominator of a return must share an adjustment
    basis; a split landing between them on different bases makes the ratio wrong
    while every individual number stays plausible.
    """
    if window.adjustment != ADJUSTMENT_BASIS:
        raise VintageError(
            f"{window.ticker} {as_of}: window is on {window.adjustment!r}, not the "
            f"canonical {ADJUSTMENT_BASIS!r}; both endpoints of a return must share "
            "one basis and this one cannot be compared to any other item"
        )
    bars = window.bars
    index = {bar.date: i for i, bar in enumerate(bars)}
    start = index.get(as_of)
    if start is None:
        earlier = [i for i, bar in enumerate(bars) if bar.date <= as_of]
        if not earlier:
            raise ScoringError(f"no bar on or before {as_of} for {window.ticker}")
        start = max(earlier)

    opening = bars[start].close
    if abs(opening - spot) / spot > SPOT_TOLERANCE:
        raise SpotDriftError(
            f"{window.ticker} {as_of}: forecast recorded spot {spot:.4f} but the "
            f"price series now closes at {opening:.4f} — the corpus would be scored "
            f"against a different series than it was produced from"
        )

    end = start + horizon_days
    if end >= len(bars):
        raise WindowNotClosedError(
            f"{window.ticker} {as_of}: needs {horizon_days} bars after {bars[start].date}, "
            f"series has {len(bars) - start - 1}"
        )
    return math.log(bars[end].close / opening)


def realised_bar(window: PriceWindow, as_of: date, horizon_days: int) -> Bar:
    """The bar the horizon closes on — the outcome `realised_return` divides by.

    Split out so it can be pinned and compared without recomputing the return, and
    so the pin names the same bar the score used rather than one derived separately.
    """
    bars = window.bars
    index = {bar.date: i for i, bar in enumerate(bars)}
    start = index.get(as_of)
    if start is None:
        earlier = [i for i, bar in enumerate(bars) if bar.date <= as_of]
        if not earlier:
            raise ScoringError(f"no bar on or before {as_of} for {window.ticker}")
        start = max(earlier)
    end = start + horizon_days
    if end >= len(bars):
        raise WindowNotClosedError(
            f"{window.ticker} {as_of}: needs {horizon_days} bars after {bars[start].date}, "
            f"series has {len(bars) - start - 1}"
        )
    return bars[end]


def score_item(
    forecast: Forecast,
    window: PriceWindow,
    *,
    band: str,
    past_earnings: Sequence[date] = (),
    paths: int = DEFAULT_PATHS,
    seed: int = 20260813,
    pin: PinReader | None = None,
    record_pin: PinWriter | None = None,
) -> ScoredItem:
    """Score one forecast against its outcome and the three baselines.

    `window` must span both the history the baselines need and the horizon that
    followed. Baselines are fitted on bars strictly before the forecast's `as_of`,
    which is what keeps the benchmark free of the look-ahead the corpus excludes.

    `past_earnings` must be **strictly prior** to `as_of`. It is checked here rather
    than trusted, because the multiplier only ever sees dates that happen to land in
    an already-truncated history — so a future date is silently dropped, and an
    adapter handing them over looks correct forever.
    """
    as_of = forecast.as_of.date()
    future = sorted(day for day in past_earnings if day >= as_of)
    if future:
        raise LookAheadError(
            f"{forecast.ticker} {as_of}: {len(future)} earnings date(s) at or after "
            f"the forecast opens, first {future[0]}. The multiplier is fitted on the "
            "ticker's own past windows; a future one is the look-ahead the corpus "
            "design exists to exclude, arriving through the benchmark."
        )
    outcome = realised_return(window, as_of, forecast.horizon_days, forecast.spot_price)

    # The outcome side of the anchor. Taken at first scoring because the outcome does
    # not exist when the forecast is written, and enforced from then on.
    bar = realised_bar(window, as_of, forecast.horizon_days)
    taken = RealisedPin(
        ticker=forecast.ticker,
        as_of=as_of,
        horizon_days=forecast.horizon_days,
        realised_date=bar.date,
        realised_close=bar.close,
    )
    known = pin(forecast.ticker, as_of, forecast.horizon_days) if pin is not None else None
    if known is None:
        if record_pin is not None:
            record_pin(taken)
    else:
        if known.realised_date != taken.realised_date:
            raise RealisedDriftError(
                f"{forecast.ticker} {as_of}: horizon closed on {known.realised_date} when "
                f"this item was first scored and closes on {taken.realised_date} now — the "
                "series has gained or lost bars and the horizon has been silently re-timed"
            )
        drift = abs(known.realised_close - taken.realised_close) / abs(known.realised_close)
        if drift > SPOT_TOLERANCE:
            raise RealisedDriftError(
                f"{forecast.ticker} {as_of}: realised close was {known.realised_close:.4f} "
                f"when first scored and is {taken.realised_close:.4f} now — the outcome "
                "this item is scored against has changed"
            )

    simulation = simulate(
        forecast.scenarios, horizon_days=forecast.horizon_days, paths=paths, seed=seed
    )
    prior = History(
        dates=tuple(bar.date for bar in window.bars),
        closes=np.array([bar.close for bar in window.bars], dtype=np.float64),
    ).before(as_of)

    baselines: dict[str, float] = {}
    baseline_log: dict[str, float] = {}
    baseline_dir: dict[str, float] = {}
    for name, prediction in _fit(prior, past_earnings, forecast.horizon_days):
        baselines[name] = float(crps_normal(prediction.mean, prediction.sigma, outcome))
        baseline_log[name] = float(log_score_normal(prediction.mean, prediction.sigma, outcome))
        # P(up) for a normal is the survival function at zero. Every baseline IS a
        # normal, so this is the exact directional probability, not an approximation.
        baseline_dir[name] = float(
            brier(0.5 * math.erfc(-prediction.mean / (prediction.sigma * math.sqrt(2.0))), outcome)
        )

    # Recomputed rather than plumbed out of the baseline: it is a few hundred
    # floats through `np.std`, and threading a second return value through
    # `Prediction` would put a field on every baseline that only one of them means.
    try:
        multiplier: float | None = earnings_multiplier(
            prior, past_earnings, horizon_days=forecast.horizon_days
        )
    except BaselineError:
        multiplier = None

    return ScoredItem(
        ticker=forecast.ticker,
        band=band,
        as_of=as_of,
        horizon_days=forecast.horizon_days,
        realised_return=outcome,
        day_index=(as_of - EPOCH).days,
        map_crps=crps_against(simulation, outcome),
        map_sigma=simulation.sigma,
        map_pit=float(pit(simulation.mean, simulation.sigma, outcome)),
        map_log_score=float(log_score_normal(simulation.mean, simulation.sigma, outcome)),
        map_brier=float(brier(simulation.probability_above(0.0), outcome)),
        map_probability_up=float(simulation.probability_above(0.0)),
        baseline_crps=baselines,
        baseline_log_score=baseline_log,
        baseline_brier=baseline_dir,
        provider=window.provider,
        adjustment=window.adjustment,
        earnings_multiplier=multiplier,
    )


def _fit(
    prior: History, past_earnings: Sequence[date], horizon_days: int
) -> list[tuple[str, Prediction]]:
    """Every baseline that this history can support.

    A baseline that cannot be fitted is omitted rather than defaulted. Substituting
    a guess would put a number in the comparison column that no model produced, and
    the missing-baseline count is itself a reportable fact.
    """
    out: list[tuple[str, Prediction]] = []
    builders: tuple[tuple[str, Callable[[], Prediction]], ...] = (
        ("random_walk", lambda: random_walk(prior, horizon_days=horizon_days)),
        ("garch", lambda: garch(prior, horizon_days=horizon_days)),
        (
            "earnings_scaled_random_walk",
            lambda: earnings_scaled_random_walk(prior, past_earnings, horizon_days=horizon_days),
        ),
    )
    for name, build in builders:
        try:
            out.append((name, build()))
        except BaselineError:
            continue
    return out


# Which pair of fields each scoring rule lives in. Lower is better for all three,
# so one bootstrap comparison serves them without a sign convention per metric.
_METRICS: dict[str, tuple[str, str]] = {
    "crps": ("map_crps", "baseline_crps"),
    "log score": ("map_log_score", "baseline_log_score"),
    "brier": ("map_brier", "baseline_brier"),
}


@dataclass(frozen=True)
class BandScores:
    """Every scored item in a band, plus what could not be scored and why."""

    items: tuple[ScoredItem, ...]
    unscored: dict[str, int]

    @property
    def n(self) -> int:
        return len(self.items)

    def crps(self, name: str | None = None) -> list[float]:
        """M.A.P.'s scores when `name` is None, otherwise that baseline's."""
        if name is None:
            return [item.map_crps for item in self.items]
        return [item.baseline_crps[name] for item in self.items if name in item.baseline_crps]

    def paired(self, name: str, metric: str = "crps") -> tuple[list[float], list[float], list[int]]:
        """M.A.P. and one baseline on exactly the items both scored.

        Pairing requires the same items on both sides; a baseline that failed on
        some of them must not be compared against M.A.P.'s scores on all of them.

        `metric` selects which scoring rule is paired. All three are lower-is-better,
        which is what lets one comparison routine serve them.
        """
        mine, theirs = _METRICS[metric]
        both = [i for i in self.items if name in getattr(i, theirs)]
        return (
            [float(getattr(i, mine)) for i in both],
            [float(getattr(i, theirs)[name]) for i in both],
            [i.day_index for i in both],
        )

    def scores(self, metric: str = "crps", name: str | None = None) -> list[float]:
        """M.A.P.'s scores on `metric` when `name` is None, otherwise that baseline's."""
        mine, theirs = _METRICS[metric]
        if name is None:
            return [float(getattr(item, mine)) for item in self.items]
        return [float(getattr(i, theirs)[name]) for i in self.items if name in getattr(i, theirs)]

    @property
    def day_index(self) -> list[int]:
        return [item.day_index for item in self.items]

    @property
    def directional_hits(self) -> float:
        """Correct calls, ties counted as a half. Reported alongside the rate so a
        round percentage reads as the count it came from rather than a placeholder."""
        hits = 0.0
        for item in self.items:
            up = item.realised_return > 0
            if item.map_probability_up == 0.5:
                hits += 0.5
            elif (item.map_probability_up > 0.5) == up:
                hits += 1.0
        return hits

    @property
    def conviction(self) -> tuple[float, float, float]:
        """How far from 0.5 the directional claims actually go: min, median, max.

        The diagnostic that makes a coin-flip Brier interpretable. A model that never
        leaves [0.45, 0.55] cannot beat a coin on direction no matter how right it is
        about magnitude, and that is a fact about the forecasts rather than a failure
        of the scoring rule.
        """
        values = sorted(item.map_probability_up for item in self.items)
        if not values:
            return (0.0, 0.0, 0.0)
        middle = values[len(values) // 2]
        return (values[0], middle, values[-1])

    @property
    def directional_accuracy(self) -> float:
        """How often the side with more than half the paths was the side that happened.

        Items where the model is exactly split are counted as half, rather than
        rounded to a direction it did not claim.
        """
        return self.directional_hits / len(self.items) if self.items else 0.0

    @property
    def baselines_carry_direction(self) -> bool:
        """Whether the baselines make any directional claim at all.

        All three are zero-drift by construction, so each predicts P(up) = 0.5 and
        scores exactly 0.25 on every item — which makes "M.A.P. vs random_walk on
        Brier" and "M.A.P. vs garch on Brier" the SAME comparison, printed twice.
        Checked rather than assumed, so a baseline that later gains a drift term
        goes back to being reported on its own.
        """
        scores = {round(v, 12) for item in self.items for v in item.baseline_brier.values()}
        return scores != {0.25}

    @property
    def pit_values(self) -> list[float]:
        return [item.map_pit for item in self.items]

    @property
    def multipliers(self) -> list[float]:
        """Every fitted earnings multiplier, for reporting how hard that baseline
        actually was. A band where most of them sit at 1.0 was not compared against
        a benchmark that widens — it was compared against the random walk twice."""
        return [i.earnings_multiplier for i in self.items if i.earnings_multiplier is not None]

    @property
    def neutral_multipliers(self) -> int:
        """Items whose earnings baseline declined to widen at all."""
        return sum(1 for m in self.multipliers if m == 1.0)


def score_band(
    forecasts: Sequence[tuple[Forecast, str]],
    *,
    prices: Callable[[str, date, date], PriceWindow],
    earnings: Callable[[str, date], Sequence[date]] = lambda _t, _d: (),
    history_days: int = 730,
    paths: int = DEFAULT_PATHS,
    seed: int = 20260813,
    strict: bool = True,
    pin: PinReader | None = None,
    record_pin: PinWriter | None = None,
) -> BandScores:
    """Score every forecast in a band, counting the ones that could not be.

    `prices` and `earnings` are callables rather than adapters so this module never
    imports `mapf.data` — the boundary that lets the whole pass be tested against
    generated series with no network.

    **`earnings` takes the forecast date, not only the ticker.** The signature is
    the guard: asked for "the ticker's earnings dates" an adapter returns all of
    them, because that reads as a static property of the company. Asked as of a
    date, it has to answer a point-in-time question, and a look-ahead becomes
    something a caller has to write on purpose rather than something it inherits.
    """
    from datetime import timedelta

    scored: list[ScoredItem] = []
    unscored: dict[str, int] = {}
    for forecast, band in forecasts:
        as_of = forecast.as_of.date()
        try:
            window = prices(
                forecast.ticker,
                as_of - timedelta(days=history_days),
                as_of + timedelta(days=forecast.horizon_days * 4 + 14),
            )
            scored.append(
                score_item(
                    forecast,
                    window,
                    band=band,
                    past_earnings=earnings(forecast.ticker, as_of),
                    paths=paths,
                    seed=seed,
                    pin=pin,
                    record_pin=record_pin,
                )
            )
        except MapError as error:
            reason = type(error).__name__
            unscored[reason] = unscored.get(reason, 0) + 1

    if strict:
        require_one_vintage(scored)
    return BandScores(items=tuple(scored), unscored=unscored)


def require_one_vintage(items: Sequence[ScoredItem]) -> None:
    """Every item in a band must have been priced from the same source and basis.

    Unlike the two endpoints of a single return, this does **not** hold by
    construction. `ProviderChain` fails over per call, so one ticker can be served
    by yfinance and the next by stooq; the price cache is keyed by `fetched_on`, so
    a pass spanning midnight mixes two vintages. Both produce well-formed windows
    that mean different things, and every number downstream — the paired
    difference, the leakage estimate — assumes one series.

    ADR 0012 states the obligation as "Phase 2 must refuse to score across mixed
    values". This is where it is refused.

    Called by `score_band` unless `strict=False`, which exists for one caller: the
    structural pre-flight, which needs to *report* this alongside every other problem
    rather than abort on the first. That caller runs this itself — the check is not
    skipped, only moved — so there is one implementation and no way to score a mixed
    band by forgetting.
    """
    vintages = {(item.provider, item.adjustment) for item in items}
    if len(vintages) > 1:
        listed = ", ".join(f"{p or '?'}/{a}" for p, a in sorted(vintages))
        raise VintageError(
            f"this band was priced from {len(vintages)} different series ({listed}). "
            "A paired comparison across them compares two things that were measured "
            "differently. Clear the price cache and re-score in one pass."
        )
