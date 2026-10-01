"""Price adapters, the failover chain, and the vintage-keyed parquet cache.

No network: yfinance is injected as a callable, Stooq is driven through
`httpx.MockTransport`. The cross-provider agreement test that *does* need network
lives in `tests/contract/` and is deselected by default.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pandas as pd
import pytest
from structlog.testing import capture_logs

from mapf.core.errors import (
    AllMarketDataProvidersFailedError,
    EmptyPriceWindowError,
    MalformedPriceDataError,
    MarketDataError,
    MarketDataUnavailableError,
    PriceSnapshotIncompleteError,
)
from mapf.core.models import ADJUSTMENT_BASIS, Bar, PriceWindow
from mapf.data.cache import ParquetPriceCache, PriceSnapshot, read_fetched_at
from mapf.data.providers.chain import ProviderChain
from mapf.data.providers.stooq import StooqProvider, to_stooq_symbol
from mapf.data.providers.yfinance_provider import YFinanceProvider

FIXTURES = Path(__file__).parents[1] / "fixtures" / "prices"
START, END = date(2026, 8, 3), date(2026, 8, 7)


def _yf_frame() -> pd.DataFrame:
    frame = pd.read_csv(FIXTURES / "yfinance_aapl.csv", parse_dates=["Date"])
    return frame.set_index("Date")


def _stooq_client(body: str, status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


class StubProvider:
    def __init__(
        self, name: str, window: PriceWindow | None = None, error: Exception | None = None
    ):
        self._name = name
        self._window = window
        self._error = error
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    def get_ohlcv(self, ticker: str, start: date, end: date) -> PriceWindow:
        self.calls += 1
        if self._error is not None:
            raise self._error
        assert self._window is not None
        return self._window


def _window(provider: str = "yfinance") -> PriceWindow:
    return (
        YFinanceProvider(lambda t, s, e: _yf_frame()).get_ohlcv("AAPL", START, END)
        if provider == "yfinance"
        else StooqProvider(_stooq_client((FIXTURES / "stooq_aapl.csv").read_text())).get_ohlcv(
            "AAPL", START, END
        )
    )


# ---------------------------------------------------------------------------
# yfinance adapter
# ---------------------------------------------------------------------------
def test_yfinance_normalises_into_the_canonical_basis() -> None:
    window = YFinanceProvider(lambda t, s, e: _yf_frame()).get_ohlcv("AAPL", START, END)
    assert window.adjustment == ADJUSTMENT_BASIS
    assert window.provider == "yfinance"
    assert len(window.bars) == 5
    assert window.last_trading_date == END


def test_yfinance_uses_the_split_adjusted_close_not_the_dividend_adjusted_one() -> None:
    """`Close`, not `Adj Close`. Picking the wrong column would silently change
    the basis and make every score a total-return score (ADR 0012)."""
    window = YFinanceProvider(lambda t, s, e: _yf_frame()).get_ohlcv("AAPL", START, END)
    assert window.bars[0].close == pytest.approx(208.40)  # Close
    assert window.bars[0].close != pytest.approx(207.02)  # Adj Close


def test_yfinance_failures_become_a_typed_unavailable() -> None:
    """A scraper raises anything; the chain needs one type to branch on."""

    def boom(ticker: str, start: date, end: date) -> pd.DataFrame:
        raise KeyError("Yahoo changed the page again")

    with pytest.raises(MarketDataUnavailableError, match="KeyError"):
        YFinanceProvider(boom).get_ohlcv("AAPL", START, END)


def test_yfinance_never_returns_an_empty_frame() -> None:
    with pytest.raises(EmptyPriceWindowError):
        YFinanceProvider(lambda t, s, e: pd.DataFrame()).get_ohlcv("AAPL", START, END)


def test_the_window_is_clipped_to_the_requested_range() -> None:
    """Providers interpret endpoints inconsistently; a wider window would make two
    runs cover different periods while claiming the same one."""
    window = YFinanceProvider(lambda t, s, e: _yf_frame()).get_ohlcv(
        "AAPL", date(2026, 8, 4), date(2026, 8, 6)
    )
    assert [bar.date for bar in window.bars] == [
        date(2026, 8, 4),
        date(2026, 8, 5),
        date(2026, 8, 6),
    ]


# ---------------------------------------------------------------------------
# Stooq adapter
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("ticker", "expected"),
    [("AAPL", "aapl.us"), ("aapl", "aapl.us"), ("VOD.L", "vod.l"), ("BRK.B", "brk.b")],
)
def test_stooq_symbol_mapping(ticker: str, expected: str) -> None:
    """Suffixed tickers pass through rather than being guessed at: Stooq's venue
    codes differ from Yahoo's, and a wrong guess fetches a different company."""
    assert to_stooq_symbol(ticker) == expected


def test_stooq_parses_its_csv_into_the_canonical_basis() -> None:
    client = _stooq_client((FIXTURES / "stooq_aapl.csv").read_text())
    window = StooqProvider(client).get_ohlcv("AAPL", START, END)
    assert window.provider == "stooq"
    assert window.adjustment == ADJUSTMENT_BASIS
    assert window.last_close == pytest.approx(213.1)


def test_stooq_agrees_with_yfinance_on_the_fixture_window() -> None:
    """Both publish split-adjusted closes, so the same window must match. This is
    the offline half of ADR 0003's agreement check."""
    stooq = StooqProvider(_stooq_client((FIXTURES / "stooq_aapl.csv").read_text())).get_ohlcv(
        "AAPL", START, END
    )
    yahoo = YFinanceProvider(lambda t, s, e: _yf_frame()).get_ohlcv("AAPL", START, END)
    assert [bar.close for bar in stooq.bars] == pytest.approx([bar.close for bar in yahoo.bars])


def test_stooq_reports_an_unknown_symbol_as_empty() -> None:
    """It answers 200 with a body, not a 404."""
    with pytest.raises(EmptyPriceWindowError):
        StooqProvider(_stooq_client("No data")).get_ohlcv("NOPE", START, END)


def test_stooq_http_errors_are_unavailable() -> None:
    with pytest.raises(MarketDataUnavailableError, match="HTTP 503"):
        StooqProvider(_stooq_client("", status=503)).get_ohlcv("AAPL", START, END)


# ---------------------------------------------------------------------------
# Chain
# ---------------------------------------------------------------------------
def test_the_chain_uses_the_primary_when_it_works() -> None:
    primary = StubProvider("yfinance", _window())
    fallback = StubProvider("stooq", _window("stooq"))
    window = ProviderChain([primary, fallback]).get_ohlcv("AAPL", START, END)
    assert window.provider == "yfinance"
    assert fallback.calls == 0


def test_the_chain_falls_back_and_logs_the_anomaly() -> None:
    primary = StubProvider("yfinance", error=MarketDataUnavailableError("yfinance", "throttled"))
    fallback = StubProvider("stooq", _window("stooq"))
    with capture_logs() as logs:
        window = ProviderChain([primary, fallback]).get_ohlcv("AAPL", START, END)
    assert window.provider == "stooq"
    assert any(entry["event"] == "market_data_failover" for entry in logs)


def test_the_chain_falls_back_on_an_empty_result_too() -> None:
    """An empty result from a scraper is indistinguishable from a broken one
    (ADR 0003 amendment)."""
    primary = StubProvider("yfinance", error=EmptyPriceWindowError("yfinance", "AAPL"))
    fallback = StubProvider("stooq", _window("stooq"))
    assert ProviderChain([primary, fallback]).get_ohlcv("AAPL", START, END).provider == "stooq"


def test_all_providers_failing_carries_every_cause() -> None:
    chain = ProviderChain(
        [
            StubProvider("yfinance", error=MarketDataUnavailableError("yfinance", "throttled")),
            StubProvider("stooq", error=EmptyPriceWindowError("stooq", "AAPL")),
        ]
    )
    with pytest.raises(AllMarketDataProvidersFailedError) as caught:
        chain.get_ohlcv("AAPL", START, END)
    assert set(caught.value.causes) == {"yfinance", "stooq"}


def test_a_chain_needs_a_provider() -> None:
    with pytest.raises(ValueError, match="at least one provider"):
        ProviderChain([])


def test_the_chain_never_merges_two_providers_rows() -> None:
    """One window, one provider, one basis. A merged series would carry two
    vintages under one label."""
    primary = StubProvider("yfinance", error=EmptyPriceWindowError("yfinance", "AAPL"))
    fallback = StubProvider("stooq", _window("stooq"))
    window = ProviderChain([primary, fallback]).get_ohlcv("AAPL", START, END)
    assert len({window.provider}) == 1
    assert window.provider == "stooq"


# ---------------------------------------------------------------------------
# Parquet cache — the vintage key (ADR 0012)
# ---------------------------------------------------------------------------
def test_a_same_day_refetch_is_served_from_disk(tmp_path: Path) -> None:
    inner = StubProvider("yfinance", _window())
    cache = ParquetPriceCache(inner, tmp_path, today=lambda: date(2026, 8, 11))
    first = cache.get_ohlcv("AAPL", START, END)
    second = cache.get_ohlcv("AAPL", START, END)
    assert inner.calls == 1
    assert [b.close for b in second.bars] == [b.close for b in first.bars]
    assert second.provider == "yfinance"


def test_a_different_day_is_a_different_vintage(tmp_path: Path) -> None:
    """The whole point. Adjusted prices change retroactively, so the same range
    fetched on two days is two different series and must not share a key."""
    inner = StubProvider("yfinance", _window())
    ParquetPriceCache(inner, tmp_path, today=lambda: date(2026, 8, 11)).get_ohlcv(
        "AAPL", START, END
    )
    ParquetPriceCache(inner, tmp_path, today=lambda: date(2026, 8, 12)).get_ohlcv(
        "AAPL", START, END
    )
    assert inner.calls == 2
    vintages = sorted(p.name for p in (tmp_path / "AAPL" / ADJUSTMENT_BASIS).iterdir())
    assert vintages == ["2026-08-11", "2026-08-12"]


def test_the_basis_is_in_the_path(tmp_path: Path) -> None:
    cache = ParquetPriceCache(
        StubProvider("yfinance", _window()), tmp_path, today=lambda: date(2026, 8, 11)
    )
    cache.get_ohlcv("AAPL", START, END)
    assert (tmp_path / "AAPL" / ADJUSTMENT_BASIS / "2026-08-11").is_dir()


def test_an_older_vintage_is_not_overwritten(tmp_path: Path) -> None:
    """An overwritten vintage is an unreproducible run."""
    inner = StubProvider("yfinance", _window())
    ParquetPriceCache(inner, tmp_path, today=lambda: date(2026, 8, 11)).get_ohlcv(
        "AAPL", START, END
    )
    ParquetPriceCache(inner, tmp_path, today=lambda: date(2026, 8, 12)).get_ohlcv(
        "AAPL", START, END
    )
    assert len(list((tmp_path / "AAPL" / ADJUSTMENT_BASIS).iterdir())) == 2


def test_the_serving_provider_survives_a_round_trip(tmp_path: Path) -> None:
    """The manifest records which source served; losing it on a cache hit would
    make half the runs unattributable."""
    cache = ParquetPriceCache(
        StubProvider("stooq", _window("stooq")), tmp_path, today=lambda: date(2026, 8, 11)
    )
    cache.get_ohlcv("AAPL", START, END)
    assert cache.get_ohlcv("AAPL", START, END).provider == "stooq"


def test_a_corrupt_cache_file_is_a_miss(tmp_path: Path) -> None:
    inner = StubProvider("yfinance", _window())
    cache = ParquetPriceCache(inner, tmp_path, today=lambda: date(2026, 8, 11))
    cache.get_ohlcv("AAPL", START, END)
    entry = next(tmp_path.rglob("*.parquet"))
    entry.write_bytes(b"not parquet")
    with capture_logs() as logs:
        cache.get_ohlcv("AAPL", START, END)
    assert inner.calls == 2
    assert any(e["event"] == "price_cache_unreadable" for e in logs)


def test_writes_leave_no_partial_files(tmp_path: Path) -> None:
    ParquetPriceCache(
        StubProvider("yfinance", _window()), tmp_path, today=lambda: date(2026, 8, 11)
    ).get_ohlcv("AAPL", START, END)
    assert list(tmp_path.rglob("*.tmp")) == []


# ---------------------------------------------------------------------------
# Normalisation edge cases and adapter surface
# ---------------------------------------------------------------------------
def test_a_frame_without_a_date_column_is_empty_not_a_crash() -> None:
    frame = pd.DataFrame(
        {"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1]}
    )
    with pytest.raises(EmptyPriceWindowError):
        YFinanceProvider(lambda t, s, e: frame).get_ohlcv("AAPL", START, END)


def test_a_frame_missing_price_columns_is_empty_not_a_crash() -> None:
    frame = pd.DataFrame({"Date": ["2026-08-03"], "close": [1.0]})
    with pytest.raises(EmptyPriceWindowError):
        YFinanceProvider(lambda t, s, e: frame).get_ohlcv("AAPL", START, END)


def test_a_frame_entirely_outside_the_range_is_empty() -> None:
    with pytest.raises(EmptyPriceWindowError):
        YFinanceProvider(lambda t, s, e: _yf_frame()).get_ohlcv(
            "AAPL", date(2027, 1, 1), date(2027, 1, 5)
        )


def test_stooq_transport_errors_are_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(MarketDataUnavailableError, match="ConnectError"):
        StooqProvider(client).get_ohlcv("AAPL", START, END)


def test_stooq_unparseable_csv_is_unavailable() -> None:
    with pytest.raises(MarketDataUnavailableError, match="unparseable CSV"):
        StooqProvider(_stooq_client("a,b\n1,2,3\n4,5,6,7\n")).get_ohlcv("AAPL", START, END)


def test_stooq_closes_the_client_it_created() -> None:
    provider = StooqProvider()
    provider.close()
    assert provider.name == "stooq"


def test_adapters_and_the_chain_report_their_names() -> None:
    """Recorded in the manifest; a run must say which source served it."""
    assert YFinanceProvider(lambda t, s, e: _yf_frame()).name == "yfinance"
    assert ProviderChain([StubProvider("yfinance"), StubProvider("stooq")]).name == (
        "yfinance+stooq"
    )


def test_the_cache_reports_the_wrapped_provider_name(tmp_path: Path) -> None:
    cache = ParquetPriceCache(StubProvider("yfinance", _window()), tmp_path)
    assert cache.name == "yfinance"


def test_the_cache_defaults_to_the_real_clock(tmp_path: Path) -> None:
    """The default is a clock read, which is why it is injectable at all."""
    cache = ParquetPriceCache(StubProvider("yfinance", _window()), tmp_path)
    cache.get_ohlcv("AAPL", START, END)
    assert list(tmp_path.rglob("*.parquet"))


# ---------------------------------------------------------------------------
# Impossible data must fail OVER, not end the run
# ---------------------------------------------------------------------------
def test_a_bar_whose_open_exceeds_its_high_is_a_market_data_error() -> None:
    """`open` outside [low, high] is impossible, not merely surprising, and it has
    to reach the chain as a MarketDataError or the chain cannot act on it."""
    frame = _yf_frame().copy()
    frame.loc[frame.index[1], "Open"] = float(frame.loc[frame.index[1], "High"]) + 5.0

    with pytest.raises(MalformedPriceDataError) as caught:
        YFinanceProvider(lambda t, s, e: frame).get_ohlcv("AAPL", START, END)
    assert caught.value.provider == "yfinance"
    assert caught.value.ticker == "AAPL"
    assert isinstance(caught.value, MarketDataError)


def test_the_chain_fails_over_when_the_primary_serves_impossible_data() -> None:
    """The failure this fixes: on 2026-09-04 yfinance served five tickers with
    `open` above `high`, and the run died with stooq configured and never tried."""
    primary = StubProvider(
        "yfinance", None, error=MalformedPriceDataError("yfinance", "AAPL", "open above high")
    )
    fallback = StubProvider("stooq", _window("stooq"))
    window = ProviderChain([primary, fallback]).get_ohlcv("AAPL", START, END)
    assert window.provider == "stooq"
    assert fallback.calls == 1


def test_a_defect_in_our_own_code_is_not_mistaken_for_a_provider_fault() -> None:
    """Why this is translated at the provider boundary rather than by widening the
    chain to `except Exception`: a KeyError of ours must propagate, not look like
    an outage and silently fail over."""
    primary = StubProvider("yfinance", None, error=KeyError("close"))
    fallback = StubProvider("stooq", _window("stooq"))
    with pytest.raises(KeyError):
        ProviderChain([primary, fallback]).get_ohlcv("AAPL", START, END)
    assert fallback.calls == 0


# ---------------------------------------------------------------------------
# A pinned vintage is a stored snapshot, not a cache with a fixed name
# ---------------------------------------------------------------------------
def test_a_pinned_vintage_reads_the_snapshot_without_fetching(tmp_path: Path) -> None:
    inner = StubProvider("yfinance", _window())
    writable = ParquetPriceCache(inner, tmp_path, today=lambda: date(2026, 9, 4))
    writable.get_ohlcv("AAPL", START, END)
    assert inner.calls == 1

    frozen = ParquetPriceCache(inner, tmp_path, today=lambda: date(2026, 9, 4), frozen=True)
    frozen.get_ohlcv("AAPL", START, END)
    assert inner.calls == 1  # served from the snapshot, provider untouched


def test_a_pinned_vintage_refuses_a_missing_window_rather_than_fetching(
    tmp_path: Path,
) -> None:
    """The whole point. A vintage that backfills from today is the calendar-keyed
    cache wearing a fixed label, and it decays exactly as that one did: on
    2026-09-05 Yahoo rewrote SCCO's split-adjusted close and three items stopped
    matching the spot they were produced against."""
    inner = StubProvider("yfinance", _window())
    frozen = ParquetPriceCache(inner, tmp_path, today=lambda: date(2026, 9, 4), frozen=True)
    with pytest.raises(PriceSnapshotIncompleteError) as caught:
        frozen.get_ohlcv("AAPL", START, END)
    assert caught.value.ticker == "AAPL"
    assert caught.value.vintage == "2026-09-04"
    assert inner.calls == 0


def test_an_unpinned_cache_still_fetches_and_writes(tmp_path: Path) -> None:
    """Pinning is opt-in: the corpus runner and ad-hoc use keep the old behaviour."""
    inner = StubProvider("yfinance", _window())
    cache = ParquetPriceCache(inner, tmp_path, today=lambda: date(2026, 9, 4))
    cache.get_ohlcv("AAPL", START, END)
    cache.get_ohlcv("AAPL", START, END)
    assert inner.calls == 1  # second call served from disk


# ---------------------------------------------------------------------------
# A window fetched before the close is refetched once after it (ADR 0040)
# ---------------------------------------------------------------------------
DAY = date(2026, 9, 30)  # a Wednesday, in daylight time: 16:30 in New York is 20:30 UTC
FROM = DAY - timedelta(days=30)


def _at(hour: int, minute: int = 0, *, day: date = DAY) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=UTC)


class _Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now


class _Sequenced:
    """Serves one window per call, in order, like a provider whose last bar moves."""

    name = "yfinance"

    def __init__(self, *windows: PriceWindow | Exception) -> None:
        self._windows = list(windows)
        self.calls = 0

    def get_ohlcv(self, ticker: str, start: date, end: date) -> PriceWindow:
        served = self._windows[min(self.calls, len(self._windows) - 1)]
        self.calls += 1
        if isinstance(served, Exception):
            raise served
        return served


def _bars(*closes: float) -> PriceWindow:
    """One bar a day, the last on DAY, so the final close is the one in question."""
    first = DAY - timedelta(days=len(closes) - 1)
    return PriceWindow(
        ticker="AAPL",
        provider="yfinance",
        adjustment="split_adjusted",
        bars=tuple(
            Bar(
                date=first + timedelta(days=i),
                open=close,
                high=close + 1,
                low=close - 1,
                close=close,
                volume=10,
            )
            for i, close in enumerate(closes)
        ),
    )


def _cache(inner: object, root: Path, clock: _Clock, *, frozen: bool = False) -> ParquetPriceCache:
    return ParquetPriceCache(
        inner,  # type: ignore[arg-type]
        root,
        today=lambda: clock.now.date(),
        now=clock,
        frozen=frozen,
    )


def test_a_window_fetched_before_the_close_is_refetched_once_after_it(tmp_path: Path) -> None:
    """The defect. A file fetched in the morning holds no bar for today, and was
    served all evening: the close appeared the next day."""
    clock = _Clock(_at(12))  # 08:00 in New York
    inner = _Sequenced(_bars(10.0), _bars(10.0, 11.0))
    cache = _cache(inner, tmp_path, clock)

    assert cache.get_ohlcv("AAPL", FROM, DAY).last_close == 10.0
    clock.now = _at(20, 29)  # 16:29: not yet
    assert cache.get_ohlcv("AAPL", FROM, DAY).last_close == 10.0
    assert inner.calls == 1

    clock.now = _at(20, 31)
    assert cache.get_ohlcv("AAPL", FROM, DAY).last_close == 11.0
    assert inner.calls == 2


def test_the_refresh_happens_once_not_on_every_read_after_the_close(tmp_path: Path) -> None:
    clock = _Clock(_at(12))
    inner = _Sequenced(_bars(10.0), _bars(10.0, 11.0))
    cache = _cache(inner, tmp_path, clock)
    cache.get_ohlcv("AAPL", FROM, DAY)

    clock.now = _at(20, 31)
    for minute in (31, 45, 59):
        clock.now = _at(20, minute)
        cache.get_ohlcv("AAPL", FROM, DAY)
    clock.now = _at(23, 0)
    cache.get_ohlcv("AAPL", FROM, DAY)
    assert inner.calls == 2


def test_an_unfinished_bar_is_not_served_as_the_close_after_the_bell(tmp_path: Path) -> None:
    """The other face of it, and the worse one: a file fetched at 11:00 holds
    today's bar at its 11:00 price. At 17:00 `settled` accepts that bar as final."""
    clock = _Clock(_at(15))  # 11:00 in New York
    inner = _Sequenced(_bars(10.0, 10.4), _bars(10.0, 10.9))
    cache = _cache(inner, tmp_path, clock)
    assert cache.get_ohlcv("AAPL", FROM, DAY).last_close == 10.4

    clock.now = _at(21, 0)
    assert cache.get_ohlcv("AAPL", FROM, DAY).last_close == 10.9


def test_a_window_fetched_after_the_close_is_never_refetched(tmp_path: Path) -> None:
    clock = _Clock(_at(20, 45))
    inner = _Sequenced(_bars(10.0, 11.0))
    cache = _cache(inner, tmp_path, clock)
    cache.get_ohlcv("AAPL", FROM, DAY)
    clock.now = _at(23, 30)
    cache.get_ohlcv("AAPL", FROM, DAY)
    assert inner.calls == 1


def test_a_window_that_stops_before_today_is_not_waiting_for_anything(tmp_path: Path) -> None:
    """Every session in it had finished when it was fetched; the day's close is not
    in its range, so refetching would change nothing but the request count."""
    clock = _Clock(_at(12))
    inner = _Sequenced(_bars(10.0, 11.0))
    cache = _cache(inner, tmp_path, clock)
    cache.get_ohlcv("AAPL", FROM, DAY - timedelta(days=1))
    clock.now = _at(21, 0)
    cache.get_ohlcv("AAPL", FROM, DAY - timedelta(days=1))
    assert inner.calls == 1


def test_the_superseded_file_is_kept_but_never_offered_as_a_window(tmp_path: Path) -> None:
    """ADR 0012: an overwritten vintage is an unreproducible run. The morning's file
    is moved aside, and `PriceSnapshot` globs `*.parquet` so it cannot surface."""
    clock = _Clock(_at(12))
    inner = _Sequenced(_bars(10.0), _bars(10.0, 11.0))
    cache = _cache(inner, tmp_path, clock)
    cache.get_ohlcv("AAPL", FROM, DAY)
    clock.now = _at(21, 0)
    cache.get_ohlcv("AAPL", FROM, DAY)

    directory = tmp_path / "AAPL" / ADJUSTMENT_BASIS / DAY.isoformat()
    kept = list(directory.glob("*.superseded"))
    assert len(kept) == 1
    assert len(list(directory.glob("*.parquet"))) == 1
    assert PriceSnapshot(tmp_path, DAY).covering("AAPL", FROM, DAY) is not None
    assert list(tmp_path.rglob("*.tmp")) == []


def test_a_failed_refetch_leaves_the_stale_file_and_raises(tmp_path: Path) -> None:
    """Serving the morning's file would put an unfinished or missing bar back in
    front of `settled`. The run fails instead, and the next call tries again."""
    clock = _Clock(_at(12))
    outage = MarketDataUnavailableError("yfinance", "down")
    inner = _Sequenced(_bars(10.0), outage, _bars(10.0, 11.0))
    cache = _cache(inner, tmp_path, clock)
    cache.get_ohlcv("AAPL", FROM, DAY)

    clock.now = _at(21, 0)
    with pytest.raises(MarketDataUnavailableError):
        cache.get_ohlcv("AAPL", FROM, DAY)
    directory = tmp_path / "AAPL" / ADJUSTMENT_BASIS / DAY.isoformat()
    assert list(directory.glob("*.superseded")) == []
    assert cache.get_ohlcv("AAPL", FROM, DAY).last_close == 11.0


def test_a_pinned_vintage_is_never_refreshed(tmp_path: Path) -> None:
    """A snapshot that changed when read would be a different snapshot."""
    clock = _Clock(_at(12))
    inner = _Sequenced(_bars(10.0), _bars(10.0, 11.0))
    _cache(inner, tmp_path, clock).get_ohlcv("AAPL", FROM, DAY)

    clock.now = _at(21, 0)
    frozen = _cache(inner, tmp_path, clock, frozen=True)
    assert frozen.get_ohlcv("AAPL", FROM, DAY).last_close == 10.0
    assert inner.calls == 1


def test_a_file_that_does_not_record_when_it_was_fetched_is_served_as_it_is(
    tmp_path: Path,
) -> None:
    """Every vintage already on disk is one. Guessing from the modification time, which
    a copy resets, would rewrite them all on first read."""
    import pyarrow.parquet as pq

    clock = _Clock(_at(12))
    inner = _Sequenced(_bars(10.0), _bars(10.0, 11.0))
    cache = _cache(inner, tmp_path, clock)
    cache.get_ohlcv("AAPL", FROM, DAY)
    entry = next(tmp_path.rglob("*.parquet"))
    table = pq.read_table(entry)
    legacy = {k: v for k, v in table.schema.metadata.items() if k != b"mapf_fetched_at"}
    pq.write_table(table.replace_schema_metadata(legacy), entry)

    clock.now = _at(21, 0)
    assert cache.get_ohlcv("AAPL", FROM, DAY).last_close == 10.0
    assert inner.calls == 1


@pytest.mark.parametrize("stamp", [b"not a time", b"2026-09-30T12:00:00"])
def test_an_unreadable_or_zoneless_fetch_instant_counts_as_unknown(
    tmp_path: Path, stamp: bytes
) -> None:
    import pyarrow.parquet as pq

    clock = _Clock(_at(12))
    inner = _Sequenced(_bars(10.0), _bars(10.0, 11.0))
    cache = _cache(inner, tmp_path, clock)
    cache.get_ohlcv("AAPL", FROM, DAY)
    entry = next(tmp_path.rglob("*.parquet"))
    table = pq.read_table(entry)
    pq.write_table(
        table.replace_schema_metadata({**table.schema.metadata, b"mapf_fetched_at": stamp}), entry
    )

    clock.now = _at(21, 0)
    assert cache.get_ohlcv("AAPL", FROM, DAY).last_close == 10.0


def test_a_file_that_cannot_be_opened_has_no_fetch_instant(tmp_path: Path) -> None:
    assert read_fetched_at(tmp_path / "missing.parquet") is None


def test_the_fetch_instant_is_recorded_with_its_zone(tmp_path: Path) -> None:
    clock = _Clock(_at(12))
    _cache(_Sequenced(_bars(10.0)), tmp_path, clock).get_ohlcv("AAPL", FROM, DAY)
    assert read_fetched_at(next(tmp_path.rglob("*.parquet"))) == _at(12)


# ---------------------------------------------------------------------------
# PriceSnapshot — read-only lookup over one stored vintage
# ---------------------------------------------------------------------------
def _store(root: Path, ticker: str, vintage: str, first: date, sessions: int) -> None:
    """Write a window the way ParquetPriceCache would, through the cache itself."""
    last = first + timedelta(days=sessions - 1)

    class _Fixed:
        name = "yfinance"

        def get_ohlcv(self, t: str, s: date, e: date) -> PriceWindow:
            return PriceWindow(
                ticker=t,
                provider="yfinance",
                adjustment="split_adjusted",
                bars=tuple(
                    Bar(
                        date=first + timedelta(days=i),
                        open=100.0 + i,
                        high=102.0 + i,
                        low=99.0 + i,
                        close=101.0 + i,
                        volume=10,
                    )
                    for i in range(sessions)
                ),
            )

    cache = ParquetPriceCache(_Fixed(), root, today=lambda: date.fromisoformat(vintage))
    cache.get_ohlcv(ticker, first, last)


def test_the_snapshot_finds_a_window_spanning_the_range(tmp_path: Path) -> None:
    _store(tmp_path, "AAPL", "2026-09-05", date(2026, 8, 3), 20)

    window = PriceSnapshot(tmp_path, date(2026, 9, 5)).covering(
        "AAPL", date(2026, 8, 10), date(2026, 8, 10)
    )

    assert window is not None
    assert window.ticker == "AAPL"
    # From the parquet's own metadata, never from a caller's assumption.
    assert window.provider == "yfinance"
    assert window.adjustment == "split_adjusted"


def test_the_widest_covering_window_wins(tmp_path: Path) -> None:
    """A horizon needs bars AFTER the anchor, so reaching furthest forward is the
    property that matters — not whichever file the directory listed first."""

    _store(tmp_path, "AAPL", "2026-09-05", date(2026, 8, 3), 8)
    _store(tmp_path, "AAPL", "2026-09-05", date(2026, 8, 3), 25)

    window = PriceSnapshot(tmp_path, date(2026, 9, 5)).covering(
        "AAPL", date(2026, 8, 4), date(2026, 8, 4)
    )

    assert window is not None
    assert len(window.bars) == 25


def test_a_range_the_vintage_does_not_span_is_none_not_a_fetch(tmp_path: Path) -> None:
    """`None` is an answer. There is no path in this class that reaches a provider,
    which is what makes a value taken through it reproducible."""

    _store(tmp_path, "AAPL", "2026-09-05", date(2026, 8, 3), 20)
    snapshot = PriceSnapshot(tmp_path, date(2026, 9, 5))

    assert snapshot.covering("AAPL", date(2027, 1, 1), date(2027, 1, 1)) is None
    assert snapshot.covering("ZZZZ", date(2026, 8, 10), date(2026, 8, 10)) is None


def test_another_vintage_is_not_consulted(tmp_path: Path) -> None:
    """Two vintages of one ticker are the confound ADR 0012 exists for. Reaching
    into the wrong one would silently mix adjustment bases."""

    _store(tmp_path, "AAPL", "2026-08-15", date(2026, 8, 3), 20)

    assert (
        PriceSnapshot(tmp_path, date(2026, 9, 5)).covering(
            "AAPL", date(2026, 8, 10), date(2026, 8, 10)
        )
        is None
    )


def test_a_stray_filename_does_not_blind_the_vintage(tmp_path: Path) -> None:

    _store(tmp_path, "AAPL", "2026-09-05", date(2026, 8, 3), 20)
    (tmp_path / "AAPL" / "split_adjusted" / "2026-09-05" / "notes.parquet").write_bytes(b"x")

    assert (
        PriceSnapshot(tmp_path, date(2026, 9, 5)).covering(
            "AAPL", date(2026, 8, 10), date(2026, 8, 10)
        )
        is not None
    )
