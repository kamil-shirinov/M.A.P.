"""ADR 0003's cross-provider agreement check. Needs network; deselected by default.

Run with `pytest -m network`.

**Asserts on daily returns, not price levels.** Levels differ by construction the
moment a corporate action falls inside the window, and tolerance-tuning against
that is wasted effort. Returns are invariant to a uniform rescaling, so they
compare cleanly as long as no action falls *inside* the window — which is why the
window is pinned rather than relative.
"""

from __future__ import annotations

from datetime import date

import pytest

from mapf.core.models import ADJUSTMENT_BASIS
from mapf.data.providers.stooq import StooqProvider
from mapf.data.providers.yfinance_provider import YFinanceProvider

# Pinned once, deliberately. MSFT paid no dividend and had no split in this
# window. If that ever stops being true the test fails and the fixture is
# re-pinned — a legible failure rather than a mysterious tolerance drift.
TICKER = "MSFT"
START = date(2024, 2, 5)
END = date(2024, 2, 9)

TOLERANCE = 1e-4


def _returns(closes: list[float]) -> list[float]:
    return [later / earlier - 1.0 for earlier, later in zip(closes, closes[1:], strict=False)]


@pytest.mark.network
def test_both_providers_agree_on_daily_returns() -> None:
    yahoo = YFinanceProvider().get_ohlcv(TICKER, START, END)
    stooq = StooqProvider().get_ohlcv(TICKER, START, END)

    assert yahoo.adjustment == stooq.adjustment == ADJUSTMENT_BASIS
    assert [bar.date for bar in yahoo.bars] == [bar.date for bar in stooq.bars]

    yahoo_returns = _returns([bar.close for bar in yahoo.bars])
    stooq_returns = _returns([bar.close for bar in stooq.bars])
    assert yahoo_returns == pytest.approx(stooq_returns, abs=TOLERANCE)


@pytest.mark.network
def test_each_provider_reports_itself() -> None:
    """A run must be able to say which source served it (ADR 0012)."""
    assert YFinanceProvider().get_ohlcv(TICKER, START, END).provider == "yfinance"
    assert StooqProvider().get_ohlcv(TICKER, START, END).provider == "stooq"
