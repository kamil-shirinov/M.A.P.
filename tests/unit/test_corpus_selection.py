"""Corpus selection, tested for the properties that make it a pre-registration.

The assertions here are about structure, not about any particular ticker list: that
the same seed reproduces the same corpus, that a ticker cannot enter one band
without the other, that a split follows the ticker rather than the band, and that
every name that fell out is accounted for with a reason.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import pytest
from pydantic import ValidationError

from mapf.core.models import EarningsFiling
from mapf.corpus.selection import (
    Band,
    Corpus,
    SelectionCriteria,
    seeded_ordering,
    select,
)

CLEAN = Band(name="clean", first_open=date(2026, 1, 1), last_open=date(2026, 8, 6))
AMBIG = Band(name="ambiguous", first_open=date(2025, 1, 1), last_open=date(2025, 12, 31))

UNIVERSE = [f"T{i:03d}" for i in range(60)]


class FakeFilings:
    """Three filings per band by default; overrides carve out the exceptions."""

    def __init__(self, overrides: dict[tuple[str, str], int] | None = None) -> None:
        self.overrides = overrides or {}
        self.calls: list[tuple[str, date, date]] = []

    def earnings_dates(self, ticker: str, start: date, end: date) -> tuple[date, ...]:
        return tuple(f.filed for f in self.earnings_filings(ticker, start, end))

    def earnings_filings(self, ticker: str, start: date, end: date) -> tuple[EarningsFiling, ...]:
        self.calls.append((ticker, start, end))
        band = "clean" if start.year == 2026 else "ambiguous"
        n = self.overrides.get((ticker, band), 3 if band == "clean" else 6)
        return tuple(
            EarningsFiling(
                accession=f"0000000001-26-{start.year * 10 + i:06d}",
                cik=1,
                filed=date(start.year, 1 + 2 * i, 15),
            )
            for i in range(n)
        )


class FakeExhibits:
    """Every filing has an exhibit unless the ticker is named as lacking them."""

    def __init__(self, without: set[str] | None = None, partial: dict[str, int] | None = None):
        self.without = without or set()
        self.partial = partial or {}
        self.seen: list[str] = []

    def has_exhibit(self, filing: EarningsFiling) -> bool:
        self.seen.append(filing.accession)
        return True


class FakeLiquidity:
    def __init__(
        self,
        missing: set[str] | None = None,
        thin: dict[str, float] | None = None,
    ) -> None:
        self.missing = missing or set()
        self.thin = thin or {}
        self.windows: list[tuple[date, date]] = []

    def median_dollar_volume(self, ticker: str, start: date, end: date) -> float | None:
        self.windows.append((start, end))
        if ticker in self.missing:
            return None
        return self.thin.get(ticker, 500_000_000.0)


def _criteria(**over: object) -> SelectionCriteria:
    kwargs: dict[str, object] = {
        "bands": (CLEAN, AMBIG),
        "seed": 20260813,
        "target_tickers": 10,
        "min_filings_per_band": 2,
    }
    kwargs.update(over)
    return SelectionCriteria.model_validate(kwargs)


def _select(
    filings: FakeFilings | None = None,
    liquidity: FakeLiquidity | None = None,
    candidates: Sequence[str] | None = None,
    exhibits: object | None = None,
    **over: object,
) -> Corpus:
    return select(
        list(candidates if candidates is not None else UNIVERSE),
        criteria=_criteria(**over),
        filings=filings or FakeFilings(),
        liquidity=liquidity or FakeLiquidity(),
        exhibits=exhibits,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Determinism — the corpus must be reproducible from the seed alone
# ---------------------------------------------------------------------------
def test_the_same_seed_reproduces_the_same_corpus() -> None:
    assert _select().model_dump() == _select().model_dump()


def test_the_ordering_does_not_depend_on_the_order_candidates_arrive_in() -> None:
    forward = seeded_ordering(UNIVERSE, 7)
    backward = seeded_ordering(list(reversed(UNIVERSE)), 7)
    assert forward == backward


def test_a_different_seed_gives_a_different_ordering() -> None:
    assert seeded_ordering(UNIVERSE, 1) != seeded_ordering(UNIVERSE, 2)


def test_the_ordering_digest_is_recorded() -> None:
    """The digest is what lets a reader verify the sequence was not edited."""
    corpus = _select()
    assert len(corpus.ordering_sha256) == 64


# ---------------------------------------------------------------------------
# Constraint 1 — the same tickers in both bands
# ---------------------------------------------------------------------------
def test_every_accepted_ticker_appears_in_both_bands() -> None:
    corpus = _select()
    for plan in corpus.accepted:
        assert {b.band for b in plan.filings} == {"clean", "ambiguous"}


def test_a_ticker_with_filings_in_only_one_band_is_rejected() -> None:
    """The leakage number is a difference, so composition must not vary across it."""
    victim = seeded_ordering(UNIVERSE, 20260813)[1]
    corpus = _select(filings=FakeFilings(overrides={(victim, "clean"): 0}))
    assert victim not in {p.ticker for p in corpus.accepted}
    rejection = next(r for r in corpus.rejected if r.ticker == victim)
    assert rejection.reason == "too_few_filings"
    assert "clean=0" in rejection.detail


def test_the_shortfall_detail_names_the_band_that_failed() -> None:
    victim = seeded_ordering(UNIVERSE, 20260813)[1]
    corpus = _select(filings=FakeFilings(overrides={(victim, "ambiguous"): 1}))
    rejection = next(r for r in corpus.rejected if r.ticker == victim)
    assert "ambiguous=1" in rejection.detail


# ---------------------------------------------------------------------------
# Constraint 2 — one split per ticker, shared across bands
# ---------------------------------------------------------------------------
def test_a_ticker_carries_one_split_for_both_bands() -> None:
    """A split is a property of the ticker; there is no per-band assignment to
    disagree with, which is what makes the confound structurally impossible."""
    corpus = _select()
    for plan in corpus.accepted:
        assert plan.split in {"dev", "holdout"}
        assert isinstance(plan.split, str)


def test_the_split_is_balanced() -> None:
    corpus = _select(target_tickers=10)
    dev = sum(1 for p in corpus.accepted if p.split == "dev")
    assert dev == len(corpus.accepted) - dev


def test_the_split_stays_balanced_when_tickers_are_rejected() -> None:
    """Alternating along the acceptance order, not hashing, is what holds this."""
    liquidity = FakeLiquidity(missing=set(UNIVERSE[:20]))
    corpus = _select(liquidity=liquidity, target_tickers=8)
    dev = sum(1 for p in corpus.accepted if p.split == "dev")
    assert len(corpus.accepted) == 8
    assert dev == 4


# ---------------------------------------------------------------------------
# Constraint 3 — replacements come from the pre-registered ordering
# ---------------------------------------------------------------------------
def test_a_rejected_ticker_is_replaced_by_the_next_name_in_sequence() -> None:
    ordering = seeded_ordering(UNIVERSE, 20260813)
    baseline = _select(target_tickers=5)
    assert [p.ticker for p in baseline.accepted] == list(ordering[:5])

    # Knock out the third: the fill must be ordering[5], never a hand-picked name.
    victim = ordering[2]
    corpus = _select(liquidity=FakeLiquidity(missing={victim}), target_tickers=5)
    assert [p.ticker for p in corpus.accepted] == [
        ordering[0],
        ordering[1],
        ordering[3],
        ordering[4],
        ordering[5],
    ]


def test_every_rejection_carries_a_reason() -> None:
    victim = seeded_ordering(UNIVERSE, 20260813)[1]
    corpus = _select(liquidity=FakeLiquidity(missing={victim}), target_tickers=5)
    assert all(r.reason for r in corpus.rejected)
    assert next(r for r in corpus.rejected if r.ticker == victim).reason == "no_price_history"


def test_candidates_outside_the_sec_index_are_rejected_as_no_cik() -> None:
    corpus = select(
        ["AAPL", "NOTREAL"],
        criteria=_criteria(target_tickers=2),
        filings=FakeFilings(),
        liquidity=FakeLiquidity(),
        ciks={"AAPL": 320193},
    )
    assert [p.ticker for p in corpus.accepted] == ["AAPL"]
    assert next(r for r in corpus.rejected if r.ticker == "NOTREAL").reason == "no_cik"


def test_names_never_examined_are_recorded_as_not_reached() -> None:
    """Attrition must account for the whole universe, including the untouched tail."""
    corpus = _select(target_tickers=5)
    assert len(corpus.accepted) + len(corpus.rejected) == len(UNIVERSE)
    assert any(r.reason == "not_reached" for r in corpus.rejected)


# ---------------------------------------------------------------------------
# Band matching and cost
# ---------------------------------------------------------------------------
def test_the_longer_band_is_capped_to_the_shorter_one() -> None:
    corpus = _select()
    for plan in corpus.accepted:
        by_band = {b.band: b.dates for b in plan.filings}
        assert len(by_band["ambiguous"]) == len(by_band["clean"])


def test_uncapped_selection_keeps_every_filing() -> None:
    corpus = _select(match_band_counts=False)
    by_band = {b.band: b.dates for b in corpus.accepted[0].filings}
    assert len(by_band["ambiguous"]) == 6
    assert len(by_band["clean"]) == 3


def test_filings_outside_the_band_are_discarded() -> None:
    """A source that over-returns must not widen the band silently."""

    class Sloppy(FakeFilings):
        def earnings_dates(self, ticker: str, start: date, end: date) -> tuple[date, ...]:
            return (*super().earnings_dates(ticker, start, end), date(2020, 1, 1))

    corpus = _select(filings=Sloppy())
    for plan in corpus.accepted:
        for band in plan.filings:
            assert all(d.year >= 2025 for d in band.dates)


def test_duplicate_filing_dates_are_collapsed() -> None:
    class Duplicating(FakeFilings):
        def earnings_dates(self, ticker: str, start: date, end: date) -> tuple[date, ...]:
            dates = super().earnings_dates(ticker, start, end)
            return dates + dates

    corpus = _select(filings=Duplicating(), match_band_counts=False)
    for plan in corpus.accepted:
        for band in plan.filings:
            assert len(set(band.dates)) == len(band.dates)


def test_total_forecasts_counts_both_bands() -> None:
    corpus = _select(target_tickers=4)
    assert corpus.total_forecasts == sum(p.total_forecasts for p in corpus.accepted)
    assert corpus.total_forecasts == 4 * 6  # 3 clean + 3 ambiguous, capped


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def test_a_band_that_ends_before_it_starts_is_rejected() -> None:
    with pytest.raises(ValidationError, match="ends before it starts"):
        Band(name="bad", first_open=date(2026, 5, 1), last_open=date(2026, 1, 1))


def test_two_bands_with_the_same_name_are_rejected() -> None:
    with pytest.raises(ValidationError, match="distinct names"):
        _criteria(bands=(CLEAN, CLEAN))


def test_split_of_returns_none_for_an_unknown_ticker() -> None:
    assert _select(target_tickers=3).split_of("NOSUCH") is None


def test_split_of_finds_an_accepted_ticker() -> None:
    corpus = _select(target_tickers=3)
    assert corpus.split_of(corpus.accepted[0].ticker) == corpus.accepted[0].split


def test_a_band_with_fewer_filings_than_the_cap_is_left_alone() -> None:
    """The cap only ever removes; it must never invent dates to reach a count."""
    ordering = seeded_ordering(UNIVERSE, 20260813)
    lean = {(t, "ambiguous"): 2 for t in ordering[:3]}
    corpus = _select(filings=FakeFilings(overrides=lean), target_tickers=3)
    for plan in corpus.accepted:
        by_band = {b.band: b.dates for b in plan.filings}
        assert len(by_band["ambiguous"]) == 2
        assert len(by_band["clean"]) == 3


# ---------------------------------------------------------------------------
# The liquidity screen
# ---------------------------------------------------------------------------
def test_a_thinly_traded_name_is_rejected_as_illiquid() -> None:
    """A seeded draw from every US filer is mostly micro-caps, whose volatility is
    nowhere near the large-cap figure the power analysis assumes."""
    victim = seeded_ordering(UNIVERSE, 20260813)[1]
    corpus = _select(liquidity=FakeLiquidity(thin={victim: 1_000_000.0}), target_tickers=5)
    rejection = next(r for r in corpus.rejected if r.ticker == victim)
    assert rejection.reason == "illiquid"
    assert "$1,000,000/day" in rejection.detail


def test_no_history_is_distinguished_from_illiquid() -> None:
    order = seeded_ordering(UNIVERSE, 20260813)
    corpus = _select(
        liquidity=FakeLiquidity(missing={order[0]}, thin={order[1]: 1.0}),
        target_tickers=4,
    )
    reasons = {r.ticker: r.reason for r in corpus.rejected}
    assert reasons[order[0]] == "no_price_history"
    assert reasons[order[1]] == "illiquid"


def test_the_screen_window_closes_before_either_band_opens() -> None:
    """Screening on data from inside a band would select on the period forecast."""
    liquidity = FakeLiquidity()
    _select(liquidity=liquidity, target_tickers=3)
    start, end = liquidity.windows[0]
    assert end < AMBIG.first_open
    assert end < CLEAN.first_open
    assert start < end


def test_a_name_exactly_at_the_floor_is_kept() -> None:
    victim = seeded_ordering(UNIVERSE, 20260813)[0]
    corpus = _select(
        liquidity=FakeLiquidity(thin={victim: 50_000_000.0}),
        target_tickers=3,
        min_median_dollar_volume=50_000_000.0,
    )
    assert victim in {p.ticker for p in corpus.accepted}


# ---------------------------------------------------------------------------
# Exhibit availability — a company property, screened rather than discovered
# ---------------------------------------------------------------------------
class ByTickerExhibits:
    """Grants exhibits to every filing except the tickers named."""

    def __init__(self, without: set[str], owner: dict[str, str]) -> None:
        self.without, self.owner = without, owner

    def has_exhibit(self, filing: EarningsFiling) -> bool:
        return self.owner.get(filing.accession, "") not in self.without


class TaggedFilings(FakeFilings):
    """Filings whose accessions record which ticker produced them."""

    def __init__(self) -> None:
        super().__init__()
        self.owner: dict[str, str] = {}
        # Stable ids: hash() is randomised per process, so two tickers could collide
        # onto one accession and the ownership assertion would fail intermittently.
        self._ids: dict[str, int] = {}

    def earnings_filings(self, ticker: str, start: date, end: date) -> tuple[EarningsFiling, ...]:
        found = super().earnings_filings(ticker, start, end)
        out = []
        for i, f in enumerate(found):
            ident = self._ids.setdefault(ticker, len(self._ids))
            accession = f"{ident:010d}-26-{start.year * 10 + i:06d}"
            self.owner[accession] = ticker
            out.append(EarningsFiling(accession=accession, cik=f.cik, filed=f.filed))
        return tuple(out)


def test_a_filer_that_never_attaches_ex_99_1_is_rejected_at_selection() -> None:
    """Deterministic company behaviour, so it belongs in selection rather than
    being discovered as run-time attrition."""
    order = seeded_ordering(UNIVERSE, 20260813)
    filings = TaggedFilings()
    corpus = _select(
        filings=filings,
        target_tickers=5,
        exhibits=ByTickerExhibits({order[1]}, filings.owner),
    )
    assert order[1] not in {p.ticker for p in corpus.accepted}
    rejection = next(r for r in corpus.rejected if r.ticker == order[1])
    assert rejection.reason == "no_exhibit"
    assert "EX-99.1" in rejection.detail


def test_a_replacement_must_clear_the_exhibit_check_too() -> None:
    """Otherwise a failing ticker is replaced by another failing ticker."""
    order = seeded_ordering(UNIVERSE, 20260813)
    filings = TaggedFilings()
    corpus = _select(
        filings=filings,
        target_tickers=3,
        exhibits=ByTickerExhibits({order[0], order[1]}, filings.owner),
    )
    assert [p.ticker for p in corpus.accepted] == [order[2], order[3], order[4]]


def test_without_an_exhibit_check_selection_is_unchanged() -> None:
    assert _select(target_tickers=5).accepted == _select(target_tickers=5, exhibits=None).accepted


# ---------------------------------------------------------------------------
# CIK uniqueness — dual-class listings are one company
# ---------------------------------------------------------------------------
def test_a_second_share_class_of_an_accepted_company_is_rejected() -> None:
    """BRK-A and BRK-B file one 8-K with one exhibit. Admitting both would put the
    same document in the corpus twice and count it as two observations."""
    corpus = select(
        ["BRK-A", "BRK-B", "AAPL"],
        criteria=_criteria(target_tickers=3),
        filings=FakeFilings(),
        liquidity=FakeLiquidity(),
        ciks={"BRK-A": 1067983, "BRK-B": 1067983, "AAPL": 320193},
    )
    accepted = [p.ticker for p in corpus.accepted]
    assert len(accepted) == 2
    assert "AAPL" in accepted
    assert len({p.cik for p in corpus.accepted}) == 2
    dupe = next(r for r in corpus.rejected if r.reason == "duplicate_cik")
    assert dupe.ticker in {"BRK-A", "BRK-B"}


def test_the_class_kept_is_the_one_the_ordering_reached_first() -> None:
    """Not the larger, cheaper or more liquid one — judgement in selection is what
    pre-registration exists to remove."""
    ciks = {"BRK-A": 1067983, "BRK-B": 1067983}
    first = next(t for t in seeded_ordering(list(ciks), 20260813) if t in ciks)
    corpus = select(
        list(ciks),
        criteria=_criteria(target_tickers=2),
        filings=FakeFilings(),
        liquidity=FakeLiquidity(),
        ciks=ciks,
    )
    assert [p.ticker for p in corpus.accepted] == [first]


def test_the_cik_is_recorded_on_the_accepted_plan() -> None:
    corpus = select(
        ["AAPL"],
        criteria=_criteria(target_tickers=1),
        filings=FakeFilings(),
        liquidity=FakeLiquidity(),
        ciks={"AAPL": 320193},
    )
    assert corpus.accepted[0].cik == 320193


# ---------------------------------------------------------------------------
# Accessions travel with dates
# ---------------------------------------------------------------------------
def test_accessions_are_recorded_alongside_dates() -> None:
    corpus = _select(target_tickers=2)
    for plan in corpus.accepted:
        for band in plan.filings:
            assert len(band.accessions) == len(band.dates)


def test_the_band_cap_keeps_dates_paired_with_their_accessions() -> None:
    """Sampling dates and accessions separately would silently mismatch them."""
    filings = TaggedFilings()
    corpus = _select(filings=filings, target_tickers=2)
    for plan in corpus.accepted:
        for band in plan.filings:
            for accession, day in zip(band.accessions, band.dates, strict=True):
                assert filings.owner[accession] == plan.ticker
                assert day.year in (2025, 2026)


def test_two_filings_on_one_date_become_one_window() -> None:
    class SameDay(FakeFilings):
        def earnings_filings(
            self, ticker: str, start: date, end: date
        ) -> tuple[EarningsFiling, ...]:
            base = super().earnings_filings(ticker, start, end)
            extra = EarningsFiling(accession="0000000009-26-999999", cik=1, filed=base[0].filed)
            return (*base, extra)

    corpus = _select(filings=SameDay(), target_tickers=1, match_band_counts=False)
    clean = next(b for b in corpus.accepted[0].filings if b.band == "clean")
    assert len(clean.dates) == len(set(clean.dates))
