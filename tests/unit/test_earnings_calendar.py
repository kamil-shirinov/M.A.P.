"""The EDGAR earnings calendar the multiplier baseline is fitted on (ADR 0023).

The baseline exists to be the benchmark that **widens for a scheduled event**. If
its multiplier sits at 1.0 it is the random walk under a second name, and beating it
means nothing. The calendar is what decides that, so these tests are about the input
to a benchmark rather than about a data adapter.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from mapf.data.earnings import DEFAULT_LOOKBACK_DAYS, EdgarEarningsCalendar
from mapf.data.filings import FilingsError, UnknownFilerError
from mapf.eval.baselines import History, earnings_multiplier

AS_OF = date(2026, 2, 2)
QUARTERS = tuple(AS_OF - timedelta(days=91 * i) for i in range(1, 13))


class _Filings:
    """Records what it was asked, so caching can be asserted on calls not results."""

    def __init__(self, dates: tuple[date, ...] = QUARTERS, error: Exception | None = None) -> None:
        self._dates = dates
        self._error = error
        self.calls: list[tuple[str, date, date]] = []

    def earnings_dates(self, ticker: str, start: date, end: date) -> tuple[date, ...]:
        self.calls.append((ticker, start, end))
        if self._error is not None:
            raise self._error
        return tuple(d for d in self._dates if start <= d <= end)


def _calendar(tmp_path: Path, filings: _Filings) -> EdgarEarningsCalendar:
    return EdgarEarningsCalendar(filings, cache_dir=tmp_path / "earnings")


# ---------------------------------------------------------------------------
# Point-in-time
# ---------------------------------------------------------------------------
def test_only_dates_strictly_before_the_forecast_are_returned(tmp_path: Path) -> None:
    filings = _Filings(dates=(*QUARTERS, AS_OF, AS_OF + timedelta(days=30)))
    got = _calendar(tmp_path, filings).dates_before("AAPL", AS_OF)
    assert all(day < AS_OF for day in got)


def test_the_forecast_date_itself_is_excluded(tmp_path: Path) -> None:
    """Strictly before. A filing on the day the forecast opens is the event being
    forecast, not evidence about how wide past ones were."""
    filings = _Filings(dates=(AS_OF,))
    assert _calendar(tmp_path, filings).dates_before("AAPL", AS_OF) == ()


def test_an_earlier_as_of_sees_less_of_the_same_calendar(tmp_path: Path) -> None:
    """The property that makes this point-in-time rather than static: one cached
    calendar, two forecast dates, two different answers."""
    calendar = _calendar(tmp_path, _Filings())
    early = calendar.dates_before("AAPL", AS_OF - timedelta(days=400))
    late = calendar.dates_before("AAPL", AS_OF)
    assert set(early) < set(late)


# ---------------------------------------------------------------------------
# Fetched once
# ---------------------------------------------------------------------------
def test_a_ticker_is_fetched_once_however_many_items_it_has(tmp_path: Path) -> None:
    """Scoring touches each ticker several times. A refetch per item would be slow
    and — if EDGAR's answer moved between calls — a different benchmark for two
    items of the same ticker."""
    filings = _Filings()
    calendar = _calendar(tmp_path, filings)
    for _ in range(5):
        calendar.dates_before("AAPL", AS_OF)
    assert len(filings.calls) == 1


def test_a_second_process_reads_the_cache_rather_than_refetching(tmp_path: Path) -> None:
    _calendar(tmp_path, _Filings()).dates_before("AAPL", AS_OF)
    fresh = _Filings()
    assert _calendar(tmp_path, fresh).dates_before("AAPL", AS_OF)
    assert fresh.calls == []


def test_the_fetch_reaches_back_past_the_fitting_window(tmp_path: Path) -> None:
    """A date outside the price history cannot be used, so the lookback need only
    cover it — with margin for a filer whose quarter lands just outside."""
    filings = _Filings()
    _calendar(tmp_path, filings).dates_before("AAPL", AS_OF)
    _, start, end = filings.calls[0]
    assert (end - start).days == DEFAULT_LOOKBACK_DAYS
    assert DEFAULT_LOOKBACK_DAYS > 730


def test_a_cache_narrower_than_the_question_is_refetched(tmp_path: Path) -> None:
    """A narrower cached range is not a partial answer to a wider question — it is a
    different calendar, and reusing it would sort the uncovered earnings windows
    into the ordinary bucket."""
    directory = tmp_path / "earnings"
    directory.mkdir()
    (directory / "AAPL.json").write_text(
        json.dumps(
            {
                "ticker": "AAPL",
                "start": (AS_OF - timedelta(days=200)).isoformat(),
                "end": AS_OF.isoformat(),
                "dates": [QUARTERS[0].isoformat()],
            }
        ),
        encoding="utf-8",
    )
    filings = _Filings()
    _calendar(tmp_path, filings).dates_before("AAPL", AS_OF)
    assert len(filings.calls) == 1


def test_a_corrupt_cache_file_is_refetched_rather_than_raised(tmp_path: Path) -> None:
    directory = tmp_path / "earnings"
    directory.mkdir()
    (directory / "AAPL.json").write_text("{not json", encoding="utf-8")
    filings = _Filings()
    assert _calendar(tmp_path, filings).dates_before("AAPL", AS_OF)
    assert len(filings.calls) == 1


# ---------------------------------------------------------------------------
# Failure is counted, never swallowed
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "error", [UnknownFilerError("no CIK"), FilingsError("EDGAR request failed")]
)
def test_a_ticker_edgar_cannot_answer_for_is_recorded(tmp_path: Path, error: Exception) -> None:
    """Empty is a legitimate answer — the multiplier falls back to a neutral 1.0 —
    but it is the answer that quietly weakens the benchmark, so it is counted."""
    calendar = _calendar(tmp_path, _Filings(error=error))
    assert calendar.dates_before("AAPL", AS_OF) == ()
    assert "AAPL" in calendar.failures


def test_a_filer_with_no_item_202_filings_is_recorded(tmp_path: Path) -> None:
    calendar = _calendar(tmp_path, _Filings(dates=()))
    assert calendar.dates_before("AAPL", AS_OF) == ()
    assert "AAPL" in calendar.failures


def test_a_failure_is_not_cached_as_an_empty_calendar(tmp_path: Path) -> None:
    """An outage must not be written to disk as "this filer has no earnings"."""
    _calendar(tmp_path, _Filings(error=FilingsError("down"))).dates_before("AAPL", AS_OF)
    assert not (tmp_path / "earnings" / "AAPL.json").exists()


def test_a_wiring_error_is_not_mistaken_for_a_missing_filer(tmp_path: Path) -> None:
    calendar = EdgarEarningsCalendar(object(), cache_dir=tmp_path)
    calendar.dates_before("AAPL", AS_OF)
    assert "cannot list earnings dates" in calendar.failures["AAPL"]


# ---------------------------------------------------------------------------
# Why completeness matters, not just coverage
# ---------------------------------------------------------------------------
def test_an_incomplete_calendar_biases_the_multiplier_toward_one() -> None:
    """The argument for fetching from EDGAR rather than from corpus membership.

    An earnings window the calendar fails to name is not merely absent — it is
    sorted into the ORDINARY bucket, raising the denominator with exactly the
    high-dispersion windows the numerator is meant to isolate. The ratio is pulled
    toward 1.0 from both ends, and a multiplier at 1.0 is a baseline that declines
    to widen for a scheduled event.
    """
    rng = np.random.default_rng(7)
    returns = rng.normal(0.0, 0.008, 620)
    events = list(range(80, 600, 63))
    for i in events:
        # Wider RETURNS in the window that opens on the event, which is what the
        # multiplier measures — a level shift would put its jump one index earlier.
        returns[i : i + 5] = rng.normal(0.0, 0.05, 5)
    closes = 100.0 * np.exp(np.cumsum(np.concatenate(([0.0], returns))))
    start = date(2024, 1, 1)
    history = History(
        dates=tuple(start + timedelta(days=i) for i in range(len(closes))),
        closes=np.asarray(closes, dtype=np.float64),
    )
    all_dates = [history.dates[i] for i in events]

    complete = earnings_multiplier(history, all_dates, horizon_days=5)
    partial = earnings_multiplier(history, all_dates[:2], horizon_days=5)

    assert complete > 1.2, "the fixture must have a real earnings effect to detect"
    assert partial < complete


# ---------------------------------------------------------------------------
# The ticker is used as a filename
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "ticker", ["../../etc/passwd", "..", "/abs", "A/B", "A\\B", "", ".hidden", "A" * 17]
)
def test_a_ticker_that_is_not_a_filename_is_refused(tmp_path: Path, ticker: str) -> None:
    """`Ticker` permits any 16 characters after upper-casing, so `../../X` is a
    valid one. Neither the frozen corpus nor EDGAR's index is attacker-controlled
    today, which is a fact about the callers rather than about this function."""
    calendar = _calendar(tmp_path, _Filings())
    assert calendar.dates_before(ticker, AS_OF) == ()
    assert ticker in calendar.failures


def test_nothing_is_written_outside_the_cache_directory(tmp_path: Path) -> None:
    root = tmp_path / "earnings"
    _calendar(tmp_path, _Filings()).dates_before("../../escaped", AS_OF)
    assert not (tmp_path.parent / "escaped.json").exists()
    assert list(root.glob("**/*.json")) == [] or all(
        p.is_relative_to(root) for p in root.glob("**/*.json")
    )


@pytest.mark.parametrize("ticker", ["AAPL", "BRK-B", "BF.B", "A"])
def test_real_tickers_still_pass(tmp_path: Path, ticker: str) -> None:
    """Dots and dashes are ordinary in US symbols; a pattern that rejected them
    would trade one defect for a broken corpus."""
    calendar = _calendar(tmp_path, _Filings())
    assert calendar.dates_before(ticker, AS_OF)
    assert ticker not in calendar.failures


def test_the_containment_check_holds_if_the_pattern_ever_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The second layer, tested by removing the first.

    Unreachable while the pattern is correct — which is the whole point of it being
    there, and also why it would otherwise be an untested line. A pattern is a claim
    about what strings look like; the containment check is about where the write
    actually goes, and only one of those is the property being protected.
    """
    monkeypatch.setattr("mapf.data.earnings._SAFE_TICKER", re.compile(r"^.*$"))
    calendar = _calendar(tmp_path, _Filings())
    assert calendar.dates_before("../escaped", AS_OF) == ()
    assert "resolves outside" in calendar.failures["../escaped"]
