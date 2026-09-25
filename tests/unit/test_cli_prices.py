"""`map prices` — a series without a forecast, and a close that keeps its date.

The command exists so a company page can show a chart before any inference runs.
The tests that matter here are not about fetching: they are about what the output
is allowed to call the number. yfinance and stooq serve *daily bars*, so the most
recent value is a close on a trading date, and on a Monday morning that date is
three days old. A field called `price` would be read as "now" and would be wrong
precisely when a gap, a halt or a stale feed makes it matter.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from mapf.cli.app import EXIT_DATA, app
from mapf.core.errors import AllMarketDataProvidersFailedError
from mapf.core.models import Bar, PriceWindow
from tests.unit.test_cli import _config

runner = CliRunner()

LAST_SESSION = date(2026, 9, 4)  # a Friday


class _StubMarket:
    """Records the window it was asked for. Never touches the network."""

    def __init__(self, sessions: int = 3) -> None:
        self.asked: tuple[str, date, date] | None = None
        self._sessions = sessions

    @property
    def name(self) -> str:
        return "yfinance"

    def get_ohlcv(self, ticker: str, start: date, end: date) -> PriceWindow:
        self.asked = (ticker, start, end)
        first = LAST_SESSION - timedelta(days=self._sessions - 1)
        return PriceWindow(
            ticker=ticker,
            provider="yfinance",
            adjustment="split_adjusted",
            bars=tuple(
                Bar(
                    date=first + timedelta(days=i),
                    open=200.0 + i,
                    high=202.0 + i,
                    low=199.0 + i,
                    close=201.0 + i,
                    volume=1_000 + i,
                )
                for i in range(self._sessions)
            ),
        )


class _Failing:
    @property
    def name(self) -> str:
        return "yfinance"

    def get_ohlcv(self, ticker: str, start: date, end: date) -> PriceWindow:
        raise AllMarketDataProvidersFailedError({"yfinance": TimeoutError("timeout")})


def _wire(monkeypatch: pytest.MonkeyPatch, market: object) -> None:
    from mapf.cli.commands import prices as prices_module

    monkeypatch.setattr(prices_module, "build_market_data", lambda s: market)


def _run(tmp_path: Path, *args: str) -> Result:
    return runner.invoke(app, ["prices", "AAPL", *args, "--config", str(_config(tmp_path))])


def test_the_json_pairs_the_close_with_the_session_it_closed_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One object, not two sibling fields: a consumer cannot destructure the value
    without also receiving the date it belongs to."""
    _wire(monkeypatch, _StubMarket())

    result = _run(tmp_path, "--json")

    assert result.exit_code == 0, result.output
    body = json.loads(result.output)
    assert body["last_close"] == {"close": 203.0, "trading_date": "2026-09-04"}


def test_no_field_anywhere_is_called_a_current_price(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A daily bar cannot support a claim about now. This is the whole point of the
    command's output shape, so it is asserted rather than left to review."""
    _wire(monkeypatch, _StubMarket())

    body = json.loads(_run(tmp_path, "--json").output)

    assert "price" not in body
    assert "current" not in json.dumps(body).lower()
    assert "spot" not in json.dumps(body).lower()


def test_the_human_output_says_last_close_and_names_the_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(monkeypatch, _StubMarket())

    result = _run(tmp_path)

    assert result.exit_code == 0, result.output
    assert "last close   203.00 on 2026-09-04" in result.output
    assert "current" not in result.output.lower()


def test_the_series_carries_its_provider_and_adjustment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A close without them is not comparable to anything (ADR 0003)."""
    _wire(monkeypatch, _StubMarket())

    body = json.loads(_run(tmp_path, "--json").output)

    assert body["provider"] == "yfinance"
    assert body["adjustment"] == "split_adjusted"
    assert len(body["bars"]) == 3
    assert body["bars"][0]["volume"] == 1_000


def test_days_sets_the_window_that_is_requested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    market = _StubMarket()
    _wire(monkeypatch, market)

    _run(tmp_path, "--days", "90", "--json")

    assert market.asked is not None
    ticker, start, end = market.asked
    assert ticker == "AAPL"
    assert (end - start).days == 90


def test_the_default_window_is_180_days(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    market = _StubMarket()
    _wire(monkeypatch, market)

    _run(tmp_path, "--json")

    assert market.asked is not None
    assert (market.asked[2] - market.asked[1]).days == 180


def test_a_non_positive_window_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _wire(monkeypatch, _StubMarket())

    result = _run(tmp_path, "--days", "0")

    assert result.exit_code == 2
    assert "at least 1" in result.output


def test_a_failing_provider_chain_is_a_sentence_and_a_data_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire(monkeypatch, _Failing())

    result = _run(tmp_path)

    assert result.exit_code == EXIT_DATA
    assert "yfinance" in result.output


def test_nothing_is_written(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """It answers a data question. A run directory here would be a forecast that
    never happened."""
    _wire(monkeypatch, _StubMarket())

    _run(tmp_path, "--json")

    assert not (tmp_path / "runs").exists()


def test_the_displayed_close_is_readable_and_the_json_is_exact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real yfinance close reads back as 316.2200012207031."""

    class _Float32(_StubMarket):
        def get_ohlcv(self, ticker: str, start: date, end: date) -> PriceWindow:
            window = super().get_ohlcv(ticker, start, end)
            bars = (*window.bars[:-1], window.bars[-1].model_copy(update={"close": 316.2200012207}))
            return window.model_copy(update={"bars": bars})

    _wire(monkeypatch, _Float32())

    assert "last close   316.22 on" in _run(tmp_path).output
    assert json.loads(_run(tmp_path, "--json").output)["last_close"]["close"] == 316.2200012207
