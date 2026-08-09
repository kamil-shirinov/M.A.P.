"""The error hierarchy.

These are tested because the failover chain and the repair loop *branch* on them.
A chain that cannot distinguish "throttled, try the next provider" from "this
ticker does not exist" turns the second into a wasted round trip and a manifest
that names the wrong provider as the one that failed.

The attributes matter as much as the messages: they are what ends up in the trace.
"""

from __future__ import annotations

import pytest

from mapf.core.errors import (
    AgentError,
    AllMarketDataProvidersFailedError,
    AmbiguousSymbolError,
    ConfigurationError,
    EmptyPriceWindowError,
    ForecastRepairExhausted,
    InferenceError,
    InferenceProtocolError,
    InferenceTimeoutError,
    MapError,
    MarketDataError,
    MarketDataUnavailableError,
    ModelNotAvailableError,
    PlaceholderConfigError,
    PriceAdjustmentUnsupportedError,
    ProviderError,
    SymbolError,
    SymbolNotFoundError,
)


# ---------------------------------------------------------------------------
# Hierarchy — the shape is the contract callers catch against
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("child", "parent"),
    [
        (ConfigurationError, MapError),
        (ModelNotAvailableError, ConfigurationError),
        (PlaceholderConfigError, ConfigurationError),
        (ProviderError, MapError),
        (InferenceError, ProviderError),
        (InferenceTimeoutError, InferenceError),
        (InferenceProtocolError, InferenceError),
        (MarketDataError, ProviderError),
        (MarketDataUnavailableError, MarketDataError),
        (AllMarketDataProvidersFailedError, MarketDataError),
        (EmptyPriceWindowError, MarketDataError),
        (PriceAdjustmentUnsupportedError, MarketDataError),
        (SymbolError, MapError),
        (SymbolNotFoundError, SymbolError),
        (AmbiguousSymbolError, SymbolError),
        (AgentError, MapError),
        (ForecastRepairExhausted, AgentError),
    ],
)
def test_error_inherits_from_its_parent(child: type[Exception], parent: type[Exception]) -> None:
    assert issubclass(child, parent)


def test_a_timeout_is_not_confused_with_a_protocol_error() -> None:
    """A 12B model swap is slow; a timeout is often a cold load, not a bad server."""
    assert not issubclass(InferenceTimeoutError, InferenceProtocolError)


def test_unavailable_is_the_only_market_data_error_worth_falling_back_on() -> None:
    """Sibling, not ancestor: catching it must not also swallow an empty window
    or an unsupported adjustment, both of which the next provider will repeat."""
    assert not issubclass(EmptyPriceWindowError, MarketDataUnavailableError)
    assert not issubclass(PriceAdjustmentUnsupportedError, MarketDataUnavailableError)


# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------
def test_model_not_available_lists_what_the_server_actually_has() -> None:
    """The usual cause is a naming difference between backends, so the available
    list is the actionable part of the message."""
    err = ModelNotAvailableError("gemma4:12b", ["llama-3.2-3b", "qwen3-4b"])
    assert err.alias == "gemma4:12b"
    assert err.available == ("llama-3.2-3b", "qwen3-4b")
    assert "llama-3.2-3b, qwen3-4b" in str(err)


def test_model_not_available_handles_an_empty_server() -> None:
    assert "(none)" in str(ModelNotAvailableError("qwen3-4b", []))


def test_placeholder_config_names_the_key_and_the_value() -> None:
    err = PlaceholderConfigError("data.sec.user_agent", "REPLACE_ME ...")
    assert err.key == "data.sec.user_agent"
    assert "data.sec.user_agent" in str(err)


def test_market_data_unavailable_records_the_provider() -> None:
    err = MarketDataUnavailableError("yfinance", "throttled after 950 requests")
    assert err.provider == "yfinance"
    assert "throttled" in str(err)


def test_all_providers_failed_carries_every_cause() -> None:
    causes: dict[str, BaseException] = {
        "yfinance": MarketDataUnavailableError("yfinance", "throttled"),
        "stooq": TimeoutError("connect timeout"),
    }
    err = AllMarketDataProvidersFailedError(causes)
    assert set(err.causes) == {"yfinance", "stooq"}
    assert "yfinance" in str(err)
    assert "stooq" in str(err)


def test_all_providers_failed_copies_the_mapping() -> None:
    """The caller's dict must not be able to mutate the recorded causes."""
    causes: dict[str, BaseException] = {"yfinance": ValueError("boom")}
    err = AllMarketDataProvidersFailedError(causes)
    causes.clear()
    assert set(err.causes) == {"yfinance"}


def test_empty_price_window_names_provider_and_ticker() -> None:
    err = EmptyPriceWindowError("stooq", "AAPL")
    assert (err.provider, err.ticker) == ("stooq", "AAPL")


def test_adjustment_unsupported_names_what_was_requested() -> None:
    err = PriceAdjustmentUnsupportedError("stooq", "split_dividend_adjusted")
    assert err.requested == "split_dividend_adjusted"


def test_symbol_not_found_states_the_us_only_limitation() -> None:
    """The most likely cause of a miss is a non-US listing, so the message says so
    rather than leaving the user to conclude the tool is broken."""
    assert "US-listed" in str(SymbolNotFoundError("vodafone"))


def test_ambiguous_symbol_carries_the_candidates() -> None:
    err = AmbiguousSymbolError("apple", ["AAPL", "APLE"])
    assert err.candidates == ("AAPL", "APLE")
    assert "AAPL, APLE" in str(err)


def test_repair_exhausted_carries_attempts_errors_and_last_response() -> None:
    """The raw response is in the exception so the trace shows what the model
    actually emitted, not merely that it was rejected."""
    err = ForecastRepairExhausted(
        attempts=3,
        errors=["probability_weight values must sum to 1.0"],
        last_response='{"bullish": ...}',
    )
    assert err.attempts == 3
    assert err.last_response == '{"bullish": ...}'
    assert "after 3 attempt(s)" in str(err)
    assert "sum to 1.0" in str(err)
