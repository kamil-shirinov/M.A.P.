"""Deterministic corpus selection.

The corpus is the pre-registration. Once frozen and committed it is evidence that
the ticker list, the dates and the split were fixed before any result was seen, so
everything here is a pure function of `(candidates, seed, criteria)` and the
sources it queries — no wall clock, no hand-picked substitutions, no ordering that
depends on dictionary iteration.

Three properties are structural rather than checked afterwards (ADR 0018):

**Both bands, same tickers.** The headline leakage number is the clean-band result
minus the ambiguous-band result. If the bands drew different companies that
difference would confound leakage with ticker composition, so a ticker is accepted
only if it clears *both* bands. Requiring it inside the acceptance test is what
makes it structural; filtering afterwards would leave attrition to be discovered.

**One split per ticker, shared across bands.** A ticker in `dev` is in `dev` in both
bands, or the same confound reappears one level down.

**Replacements come from the seeded ordering.** Tickers fail — no CIK, no price
history, too few filings. Every replacement is the next name in sequence, and the
reason for each rejection is recorded, so attrition is auditable rather than a gap.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from datetime import date, timedelta
from hashlib import sha256
from typing import Literal

from pydantic import Field, model_validator

from mapf.core.models import DomainModel, Ticker
from mapf.core.ports import FilingSource, PriceAvailability

Split = Literal["dev", "holdout"]
RejectionReason = Literal[
    "no_cik",
    "no_price_history",
    "too_few_filings",
    "not_reached",
]


class Band(DomainModel):
    """A calendar window forecasts may open in.

    `last_open` is the last date a forecast may *start*, not the last date in the
    band. The caller subtracts the horizon, because only the caller knows the
    trading calendar; doing it here would need a market calendar in a module that
    is otherwise pure.
    """

    name: str = Field(min_length=1)
    first_open: date
    last_open: date

    @model_validator(mode="after")
    def _ordered(self) -> Band:
        if self.last_open < self.first_open:
            raise ValueError(f"band {self.name!r} ends before it starts")
        return self


class SelectionCriteria(DomainModel):
    bands: tuple[Band, Band]
    seed: int
    target_tickers: int = Field(default=120, ge=1)
    min_filings_per_band: int = Field(default=2, ge=1)
    history_days: int = Field(default=730, ge=1)
    # The ambiguous band is roughly twice as long, so it supplies roughly twice the
    # filings. Left uncapped it would more than double the inference bill for a
    # number that is only ever read as a difference. Capping the second band to the
    # first band's count per ticker keeps the comparison balanced and the cost
    # bounded; which filings survive the cap is chosen by the same seed.
    match_band_counts: bool = True

    @model_validator(mode="after")
    def _distinct_band_names(self) -> SelectionCriteria:
        if self.bands[0].name == self.bands[1].name:
            raise ValueError("bands must have distinct names")
        return self


class BandFilings(DomainModel):
    band: str = Field(min_length=1)
    dates: tuple[date, ...] = Field(min_length=1)


class TickerPlan(DomainModel):
    ticker: Ticker
    split: Split
    filings: tuple[BandFilings, ...] = Field(min_length=1)

    @property
    def total_forecasts(self) -> int:
        return sum(len(b.dates) for b in self.filings)


class Rejection(DomainModel):
    ticker: Ticker
    reason: RejectionReason
    detail: str = ""


class Corpus(DomainModel):
    """The frozen artifact. Committed before any inference runs."""

    criteria: SelectionCriteria
    ordering_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    accepted: tuple[TickerPlan, ...]
    rejected: tuple[Rejection, ...]

    @property
    def total_forecasts(self) -> int:
        return sum(plan.total_forecasts for plan in self.accepted)

    def split_of(self, ticker: str) -> Split | None:
        for plan in self.accepted:
            if plan.ticker == ticker:
                return plan.split
        return None


def seeded_ordering(candidates: Sequence[str], seed: int) -> tuple[str, ...]:
    """The pre-registered sequence every replacement is drawn from.

    Sorted before shuffling so the result depends on the *set* of candidates and
    the seed, never on the order they happened to arrive in.
    """
    pool = sorted({c.strip().upper() for c in candidates if c.strip()})
    rng = random.Random(seed)
    rng.shuffle(pool)
    return tuple(pool)


def _sample(dates: Sequence[date], keep: int, rng: random.Random) -> tuple[date, ...]:
    if keep >= len(dates):
        return tuple(dates)
    return tuple(sorted(rng.sample(list(dates), keep)))


def select(
    candidates: Sequence[str],
    *,
    criteria: SelectionCriteria,
    filings: FilingSource,
    prices: PriceAvailability,
    ciks: Sequence[str] | None = None,
) -> Corpus:
    """Walk the seeded ordering, accepting until the target is met.

    `ciks` is the set of tickers known to the SEC index; a candidate outside it is
    rejected as `no_cik` rather than silently queried and found empty.
    """
    ordering = seeded_ordering(candidates, criteria.seed)
    digest = sha256("\n".join(ordering).encode()).hexdigest()
    known = {c.strip().upper() for c in ciks} if ciks is not None else None
    first, second = criteria.bands

    accepted: list[TickerPlan] = []
    rejected: list[Rejection] = []

    for ticker in ordering:
        if len(accepted) >= criteria.target_tickers:
            rejected.append(Rejection(ticker=ticker, reason="not_reached"))
            continue
        if known is not None and ticker not in known:
            rejected.append(Rejection(ticker=ticker, reason="no_cik"))
            continue
        if not prices.has_history(
            ticker, _history_start(first, criteria.history_days), second.last_open
        ):
            rejected.append(Rejection(ticker=ticker, reason="no_price_history"))
            continue

        per_band: list[BandFilings] = []
        shortfall: str | None = None
        for band in (first, second):
            dates = tuple(
                d
                for d in filings.earnings_dates(ticker, band.first_open, band.last_open)
                if band.first_open <= d <= band.last_open
            )
            dates = tuple(sorted(set(dates)))
            if len(dates) < criteria.min_filings_per_band:
                shortfall = f"{band.name}={len(dates)} < {criteria.min_filings_per_band}"
                break
            per_band.append(BandFilings(band=band.name, dates=dates))

        if shortfall is not None:
            rejected.append(
                Rejection(ticker=ticker, reason="too_few_filings", detail=shortfall)
            )
            continue

        if criteria.match_band_counts:
            keep = len(per_band[0].dates)
            rng = random.Random(f"{criteria.seed}:{ticker}")
            per_band[1] = BandFilings(
                band=per_band[1].band, dates=_sample(per_band[1].dates, keep, rng)
            )

        # Alternating along the acceptance order, so the balance is exact at any
        # accepted count. Hashing the ticker would drift as tickers are rejected.
        split: Split = "dev" if len(accepted) % 2 == 0 else "holdout"
        accepted.append(
            TickerPlan(ticker=ticker, split=split, filings=tuple(per_band))
        )

    return Corpus(
        criteria=criteria,
        ordering_sha256=digest,
        accepted=tuple(accepted),
        rejected=tuple(rejected),
    )


def _history_start(band: Band, history_days: int) -> date:
    return band.first_open - timedelta(days=history_days)
