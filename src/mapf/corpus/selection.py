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
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from hashlib import sha256
from typing import Literal

from pydantic import Field, model_validator

from mapf.core.models import DomainModel, EarningsFiling, Ticker
from mapf.core.ports import ExhibitCheck, FilingSource, LiquidityScreen

Split = Literal["dev", "holdout"]
RejectionReason = Literal[
    "no_cik",
    "duplicate_cik",
    "no_price_history",
    "illiquid",
    "too_few_filings",
    "no_exhibit",
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
    history_days: int = Field(default=365, ge=1)
    # A seeded draw from every US filer is dominated by micro-caps, whose realised
    # volatility is nowhere near the large-cap 25% every power figure in ADR 0018
    # assumes. The screen keeps the assumption without making selection subjective:
    # the floor is pre-registered here and applied mechanically along the ordering.
    min_median_dollar_volume: float = Field(default=50_000_000.0, ge=0.0)
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
    # The identifiers that make an item reproducible, parallel to `dates`.
    accessions: tuple[str, ...] = ()


class TickerPlan(DomainModel):
    ticker: Ticker
    cik: int | None = None
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


def _first_per_date(found: Sequence[EarningsFiling]) -> list[EarningsFiling]:
    """One filing per date: two 8-Ks on one day are one forecast window."""
    by_date: dict[date, EarningsFiling] = {}
    for filing in sorted(found, key=lambda f: (f.filed, f.accession)):
        by_date.setdefault(filing.filed, filing)
    return [by_date[d] for d in sorted(by_date)]


def _sample_band(band: BandFilings, keep: int, rng: random.Random) -> BandFilings:
    """Down-sample a band, keeping each date paired with its accession."""
    rows = list(zip(band.dates, band.accessions, strict=True))
    rows = sorted(rng.sample(rows, keep)) if keep < len(rows) else sorted(rows)
    return BandFilings(
        band=band.band,
        dates=tuple(r[0] for r in rows),
        accessions=tuple(r[1] for r in rows),
    )


def select(
    candidates: Sequence[str],
    *,
    criteria: SelectionCriteria,
    filings: FilingSource,
    liquidity: LiquidityScreen,
    ciks: Mapping[str, int] | None = None,
    exhibits: ExhibitCheck | None = None,
) -> Corpus:
    """Walk the seeded ordering, accepting until the target is met.

    `ciks` maps ticker to CIK for every filer known to the SEC index; a candidate
    outside it is rejected as `no_cik` rather than silently queried and found empty.
    It also supplies the identity used for uniqueness: `BRK-A` and `BRK-B` are two
    listings of one company filing one 8-K, so admitting both would put the same
    document in the corpus twice and count it as two independent observations.

    The liquidity screen is measured over `history_days` ending the day before the
    earlier band opens, so selection never sees inside a forecast window.
    """
    ordering = seeded_ordering(candidates, criteria.seed)
    digest = sha256("\n".join(ordering).encode()).hexdigest()
    known = {t.strip().upper(): cik for t, cik in ciks.items()} if ciks is not None else None
    seen_ciks: set[int] = set()
    first, second = criteria.bands
    # Measured strictly before either band opens. A screen that overlapped a band
    # would select on data from the period being forecast.
    screen_end = min(first.first_open, second.first_open) - timedelta(days=1)
    screen_start = screen_end - timedelta(days=criteria.history_days)

    accepted: list[TickerPlan] = []
    rejected: list[Rejection] = []

    for ticker in ordering:
        if len(accepted) >= criteria.target_tickers:
            rejected.append(Rejection(ticker=ticker, reason="not_reached"))
            continue
        cik: int | None = None
        if known is not None:
            if ticker not in known:
                rejected.append(Rejection(ticker=ticker, reason="no_cik"))
                continue
            cik = known[ticker]
            if cik in seen_ciks:
                # A second share class of a company already accepted. One filing,
                # one exhibit, one event — not two observations.
                rejected.append(
                    Rejection(ticker=ticker, reason="duplicate_cik", detail=f"CIK {cik}")
                )
                continue
        volume = liquidity.median_dollar_volume(ticker, screen_start, screen_end)
        if volume is None:
            rejected.append(Rejection(ticker=ticker, reason="no_price_history"))
            continue
        if volume < criteria.min_median_dollar_volume:
            rejected.append(
                Rejection(
                    ticker=ticker,
                    reason="illiquid",
                    detail=f"median ${volume:,.0f}/day < ${criteria.min_median_dollar_volume:,.0f}",
                )
            )
            continue

        per_band: list[BandFilings] = []
        shortfall: str | None = None
        no_exhibit: str | None = None
        for band in (first, second):
            found = [
                f
                for f in filings.earnings_filings(ticker, band.first_open, band.last_open)
                if band.first_open <= f.filed <= band.last_open
            ]
            usable = _first_per_date(found)
            if exhibits is not None:
                with_exhibit = [f for f in usable if exhibits.has_exhibit(f)]
                if len(with_exhibit) < criteria.min_filings_per_band:
                    no_exhibit = (
                        f"{band.name}: {len(with_exhibit)} of {len(usable)} filings carry EX-99.1"
                    )
                    break
                usable = with_exhibit
            if len(usable) < criteria.min_filings_per_band:
                shortfall = f"{band.name}={len(usable)} < {criteria.min_filings_per_band}"
                break
            per_band.append(
                BandFilings(
                    band=band.name,
                    dates=tuple(f.filed for f in usable),
                    accessions=tuple(f.accession for f in usable),
                )
            )

        if no_exhibit is not None:
            rejected.append(Rejection(ticker=ticker, reason="no_exhibit", detail=no_exhibit))
            continue
        if shortfall is not None:
            rejected.append(Rejection(ticker=ticker, reason="too_few_filings", detail=shortfall))
            continue

        if criteria.match_band_counts:
            keep = len(per_band[0].dates)
            rng = random.Random(f"{criteria.seed}:{ticker}")
            per_band[1] = _sample_band(per_band[1], keep, rng)

        # Alternating along the acceptance order, so the balance is exact at any
        # accepted count. Hashing the ticker would drift as tickers are rejected.
        split: Split = "dev" if len(accepted) % 2 == 0 else "holdout"
        if cik is not None:
            seen_ciks.add(cik)
        accepted.append(TickerPlan(ticker=ticker, cik=cik, split=split, filings=tuple(per_band)))

    return Corpus(
        criteria=criteria,
        ordering_sha256=digest,
        accepted=tuple(accepted),
        rejected=tuple(rejected),
    )
