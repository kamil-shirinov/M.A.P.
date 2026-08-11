"""The domain types outside `ScenarioSet`.

Most of these guard against a *plausible-looking* wrong value rather than a
crash: a naive timestamp, a zero-length price series, an out-of-order merge. Each
one produces a forecast that validates, serialises, and means nothing.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from mapf.core.models import (
    Bar,
    Document,
    Forecast,
    MaterialFacts,
    ModelVersions,
    PriceWindow,
    Symbol,
    UntrustedText,
)
from tests.conftest import make_scenario_set

DOC_ID = "sha256:" + "a" * 64
AS_OF = datetime(2026, 8, 9, 14, 3, tzinfo=UTC)


def _bar(day: int, close: float = 100.0) -> Bar:
    return Bar(
        date=date(2026, 8, day),
        open=close,
        high=close + 1.0,
        low=close - 1.0,
        close=close,
        volume=1_000,
    )


def _forecast(**overrides: object) -> Forecast:
    kwargs: dict[str, object] = {
        "run_id": "0d1b7d3e-6a1e-4d5f-8f4a-9c2b1a0e7f31",
        "ticker": "AAPL",
        "as_of": AS_OF,
        "horizon_days": 21,
        "spot_price": 231.45,
        "source_doc_ids": (DOC_ID,),
        "model_versions": ModelVersions(intake="a", analyst="b", structuralist="c"),
        "scenarios": make_scenario_set(),
    }
    kwargs.update(overrides)
    return Forecast.model_validate(kwargs)


# ---------------------------------------------------------------------------
# Symbol
# ---------------------------------------------------------------------------
def test_ticker_is_normalised() -> None:
    assert Symbol(ticker="  aapl  ", name="Apple Inc.").ticker == "AAPL"


def test_blank_ticker_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Symbol(ticker="   ", name="Apple Inc.")


def test_non_us_listing_needs_no_cik_or_exchange() -> None:
    """Suffixed tickers pass through without entering the SEC index."""
    symbol = Symbol(ticker="VOD.L", name="Vodafone Group plc")
    assert symbol.cik is None
    assert symbol.exchange is None


# ---------------------------------------------------------------------------
# Document
# ---------------------------------------------------------------------------
def test_document_accepts_a_sha256_prefixed_id() -> None:
    doc = Document(
        id=DOC_ID,
        source="news/reuters-2026-08-09.txt",
        text=UntrustedText("Apple announced ..."),
        fetched_at=AS_OF,
    )
    assert doc.id.startswith("sha256:")


@pytest.mark.parametrize("bad_id", ["a" * 64, "sha256:xyz", "sha256:" + "A" * 64, ""])
def test_malformed_document_ids_are_rejected(bad_id: str) -> None:
    with pytest.raises(ValidationError):
        Document(id=bad_id, source="s", text=UntrustedText("t"), fetched_at=AS_OF)


def test_naive_fetched_at_is_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        Document(
            id=DOC_ID,
            source="s",
            text=UntrustedText("t"),
            fetched_at=datetime(2026, 8, 9, 14, 3),  # noqa: DTZ001
        )


# ---------------------------------------------------------------------------
# Bar and PriceWindow
# ---------------------------------------------------------------------------
def test_close_outside_the_high_low_range_is_rejected() -> None:
    with pytest.raises(ValidationError, match="close"):
        Bar(date=date(2026, 8, 3), open=100.0, high=101.0, low=99.0, close=105.0, volume=1)


def test_open_outside_the_high_low_range_is_rejected() -> None:
    with pytest.raises(ValidationError, match="open"):
        Bar(date=date(2026, 8, 3), open=105.0, high=101.0, low=99.0, close=100.0, volume=1)


def test_low_above_high_is_rejected() -> None:
    with pytest.raises(ValidationError, match="exceeds high"):
        Bar(date=date(2026, 8, 3), open=100.0, high=99.0, low=101.0, close=100.0, volume=1)


def test_empty_price_window_is_rejected() -> None:
    """An empty series is an error, never a silently returned frame (ADR 0003)."""
    with pytest.raises(ValidationError):
        PriceWindow(ticker="AAPL", provider="yfinance", adjustment="split_adjusted", bars=())


def test_out_of_order_bars_are_rejected() -> None:
    with pytest.raises(ValidationError, match="strictly increasing"):
        PriceWindow(
            ticker="AAPL",
            provider="yfinance",
            adjustment="split_adjusted",
            bars=(_bar(4), _bar(3)),
        )


def test_duplicate_dates_are_rejected() -> None:
    """Two rows for one day means a bad merge across providers."""
    with pytest.raises(ValidationError, match="strictly increasing"):
        PriceWindow(
            ticker="AAPL",
            provider="yfinance",
            adjustment="split_adjusted",
            bars=(_bar(3), _bar(3)),
        )


def test_price_window_exposes_last_close_and_trading_date() -> None:
    window = PriceWindow(
        ticker="AAPL",
        provider="stooq",
        adjustment="split_adjusted",
        bars=(_bar(3, 100.0), _bar(4, 102.5)),
    )
    assert window.last_close == pytest.approx(102.5)
    assert window.last_trading_date == date(2026, 8, 4)


def test_unknown_adjustment_basis_is_rejected() -> None:
    with pytest.raises(ValidationError):
        PriceWindow(
            ticker="AAPL",
            provider="stooq",
            adjustment="raw",  # type: ignore[arg-type]
            bars=(_bar(3),),
        )


# ---------------------------------------------------------------------------
# MaterialFacts
# ---------------------------------------------------------------------------
def test_material_facts_require_at_least_one_fact() -> None:
    with pytest.raises(ValidationError):
        MaterialFacts(ticker="AAPL", facts=(), source_doc_ids=(DOC_ID,))


def test_material_facts_require_provenance() -> None:
    with pytest.raises(ValidationError):
        MaterialFacts(ticker="AAPL", facts=(UntrustedText("a fact"),), source_doc_ids=())


# ---------------------------------------------------------------------------
# Forecast
# ---------------------------------------------------------------------------
def test_forecast_defaults_schema_version() -> None:
    assert _forecast().schema_version == "1.0.0"


def test_naive_as_of_is_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        _forecast(as_of=datetime(2026, 8, 9, 14, 3))  # noqa: DTZ001


@pytest.mark.parametrize("horizon", [0, -1, 253])
def test_horizon_outside_one_to_252_is_rejected(horizon: int) -> None:
    with pytest.raises(ValidationError):
        _forecast(horizon_days=horizon)


@pytest.mark.parametrize("horizon", [1, 21, 252])
def test_horizon_at_the_bounds_is_accepted(horizon: int) -> None:
    assert _forecast(horizon_days=horizon).horizon_days == horizon


@pytest.mark.parametrize("spot", [0.0, -1.0])
def test_non_positive_spot_price_is_rejected(spot: float) -> None:
    """`spot_price` is what makes the forecast scoreable; zero makes every
    percentage modifier meaningless."""
    with pytest.raises(ValidationError):
        _forecast(spot_price=spot)


def test_forecast_field_order_matches_the_agreed_artifact() -> None:
    """The on-disk shape is part of the contract, not an implementation detail."""
    assert list(_forecast().model_dump().keys()) == [
        "schema_version",
        "run_id",
        "ticker",
        "as_of",
        "horizon_days",
        "spot_price",
        "source_doc_ids",
        "model_versions",
        "scenarios",
    ]


def test_forecast_round_trips_through_json() -> None:
    original = _forecast()
    assert Forecast.model_validate_json(original.model_dump_json()) == original
