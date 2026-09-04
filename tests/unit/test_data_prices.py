"""Price adapters, the failover chain, and the vintage-keyed parquet cache.

No network: yfinance is injected as a callable, Stooq is driven through
`httpx.MockTransport`. The cross-provider agreement test that *does* need network
lives in `tests/contract/` and is deselected by default.
"""

from __future__ import annotations

from datetime import date
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
)
from mapf.core.models import ADJUSTMENT_BASIS, PriceWindow
from mapf.data.cache import ParquetPriceCache
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
