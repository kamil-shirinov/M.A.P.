"""The EDGAR Item 2.02 adapter.

No network: every response is served by an `httpx.MockTransport`. The assertions
are about the item filter and the pagination decision, because both are places
where a wrong answer looks like a plausible one — a wider item filter silently
changes what a forecast window contains, and a missed archive silently shortens a
band.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import httpx
import pytest

from mapf.core.models import Symbol
from mapf.data.filings import EdgarFilings, FilingsError, UnknownFilerError
from mapf.data.symbols import Throttle

START, END = date(2025, 1, 1), date(2026, 8, 13)


class FakeSymbols:
    def __init__(self, cik: int | None = 320193) -> None:
        self.cik = cik

    def search(self, query: str, *, limit: int = 10) -> tuple[()]:  # pragma: no cover
        return ()

    def get(self, ticker: str) -> Symbol | None:
        if ticker == "NOSUCH":
            return None
        return Symbol(ticker=ticker, name="Test Co", cik=self.cik)


def _block(rows: list[tuple[str, str, str]]) -> dict[str, list[str]]:
    return {
        "form": [r[0] for r in rows],
        "filingDate": [r[1] for r in rows],
        "items": [r[2] for r in rows],
    }


def _adapter(
    handler: Callable[[httpx.Request], httpx.Response],
    symbols: FakeSymbols | None = None,
) -> EdgarFilings:
    return EdgarFilings(
        symbols or FakeSymbols(),
        user_agent="Test test@example.com",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        throttle=Throttle(1000.0, sleep=lambda _: None),
    )


def _recent(
    rows: list[tuple[str, str, str]],
    files: list[dict[str, str]] | None = None,
) -> Callable[[httpx.Request], httpx.Response]:
    payload = {"filings": {"recent": _block(rows), "files": files or []}}
    return lambda request: httpx.Response(200, json=payload)


# ---------------------------------------------------------------------------
# The item filter — the reason this adapter exists
# ---------------------------------------------------------------------------
def test_only_item_2_02_filings_are_returned() -> None:
    """5.02 and 8.01 are 8-Ks too. Including them would triple the apparent supply
    and change what a forecast window contains."""
    adapter = _adapter(
        _recent(
            [
                ("8-K", "2025-02-01", "2.02,9.01"),
                ("8-K", "2025-03-01", "5.02"),
                ("8-K", "2025-04-01", "8.01"),
                ("8-K", "2025-05-01", "2.02"),
            ]
        )
    )
    assert adapter.earnings_dates("AAPL", START, END) == (date(2025, 2, 1), date(2025, 5, 1))


def test_non_8k_forms_are_ignored() -> None:
    adapter = _adapter(
        _recent([("10-Q", "2025-02-01", "2.02"), ("8-K", "2025-03-01", "2.02")])
    )
    assert adapter.earnings_dates("AAPL", START, END) == (date(2025, 3, 1),)


def test_item_2_02_is_matched_exactly_not_as_a_substring() -> None:
    """`12.02` and `2.021` must not match. A substring test would accept both."""
    adapter = _adapter(
        _recent([("8-K", "2025-02-01", "12.02"), ("8-K", "2025-03-01", "2.02")])
    )
    assert adapter.earnings_dates("AAPL", START, END) == (date(2025, 3, 1),)


def test_whitespace_around_items_is_tolerated() -> None:
    adapter = _adapter(_recent([("8-K", "2025-02-01", "9.01, 2.02 ")]))
    assert adapter.earnings_dates("AAPL", START, END) == (date(2025, 2, 1),)


# ---------------------------------------------------------------------------
# Window and ordering
# ---------------------------------------------------------------------------
def test_filings_outside_the_window_are_dropped() -> None:
    adapter = _adapter(
        _recent([("8-K", "2019-02-01", "2.02"), ("8-K", "2025-02-01", "2.02")])
    )
    assert adapter.earnings_dates("AAPL", START, END) == (date(2025, 2, 1),)


def test_dates_are_returned_ascending_and_deduplicated() -> None:
    adapter = _adapter(
        _recent(
            [
                ("8-K", "2025-05-01", "2.02"),
                ("8-K", "2025-02-01", "2.02"),
                ("8-K", "2025-05-01", "2.02"),
            ]
        )
    )
    assert adapter.earnings_dates("AAPL", START, END) == (date(2025, 2, 1), date(2025, 5, 1))


def test_a_filer_with_no_earnings_8ks_returns_empty() -> None:
    """Empty is a legitimate answer; selection turns it into a typed rejection."""
    adapter = _adapter(_recent([("8-K", "2025-02-01", "5.02")]))
    assert adapter.earnings_dates("AAPL", START, END) == ()


# ---------------------------------------------------------------------------
# Pagination — a missed archive silently shortens a band
# ---------------------------------------------------------------------------
def test_archives_are_not_fetched_when_recent_already_covers_the_window() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(
            200,
            json={
                "filings": {
                    "recent": _block([("8-K", "2024-06-01", "2.02")]),
                    "files": [
                        {"name": "old.json", "filingFrom": "2010-01-01", "filingTo": "2018-01-01"}
                    ],
                }
            },
        )

    _adapter(handler).earnings_dates("AAPL", START, END)
    assert len(calls) == 1


def test_archives_are_fetched_when_recent_starts_after_the_window() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "archive" in str(request.url):
            return httpx.Response(200, json=_block([("8-K", "2025-02-01", "2.02")]))
        return httpx.Response(
            200,
            json={
                "filings": {
                    "recent": _block([("8-K", "2026-06-01", "2.02")]),
                    "files": [
                        {
                            "name": "archive.json",
                            "filingFrom": "2024-01-01",
                            "filingTo": "2026-01-01",
                        }
                    ],
                }
            },
        )

    dates = _adapter(handler).earnings_dates("AAPL", START, END)
    assert dates == (date(2025, 2, 1), date(2026, 6, 1))


def test_archives_outside_the_window_are_skipped() -> None:
    fetched: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        fetched.append(str(request.url))
        if "old" in str(request.url):
            return httpx.Response(200, json=_block([]))
        return httpx.Response(
            200,
            json={
                "filings": {
                    "recent": _block([("8-K", "2026-06-01", "2.02")]),
                    "files": [
                        {"name": "old.json", "filingFrom": "2001-01-01", "filingTo": "2005-01-01"}
                    ],
                }
            },
        )

    _adapter(handler).earnings_dates("AAPL", START, END)
    assert not any("old" in url for url in fetched)


def test_an_undated_archive_is_fetched_rather_than_skipped() -> None:
    """Skipping it would silently shorten the band; fetching costs one request."""
    fetched: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        fetched.append(str(request.url))
        if "mystery" in str(request.url):
            return httpx.Response(200, json=_block([("8-K", "2025-03-01", "2.02")]))
        return httpx.Response(
            200,
            json={"filings": {"recent": _block([]), "files": [{"name": "mystery.json"}]}},
        )

    assert _adapter(handler).earnings_dates("AAPL", START, END) == (date(2025, 3, 1),)
    assert any("mystery" in url for url in fetched)


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------
def test_a_ticker_with_no_cik_raises_unknown_filer() -> None:
    adapter = _adapter(_recent([]), symbols=FakeSymbols())
    with pytest.raises(UnknownFilerError, match="not in the SEC index"):
        adapter.earnings_dates("NOSUCH", START, END)


def test_a_ticker_absent_from_the_index_raises_unknown_filer() -> None:
    adapter = _adapter(_recent([]), symbols=FakeSymbols(cik=None))
    with pytest.raises(UnknownFilerError):
        adapter.earnings_dates("AAPL", START, END)


def test_an_http_error_becomes_a_filings_error() -> None:
    adapter = _adapter(lambda request: httpx.Response(403))
    with pytest.raises(FilingsError, match="EDGAR request failed"):
        adapter.earnings_dates("AAPL", START, END)


def test_a_non_object_response_is_rejected() -> None:
    adapter = _adapter(lambda request: httpx.Response(200, json=[1, 2, 3]))
    with pytest.raises(FilingsError, match="expected an object"):
        adapter.earnings_dates("AAPL", START, END)


def test_a_malformed_filing_date_does_not_kill_the_ticker() -> None:
    """One bad row must not cost the whole filer; the rest still count."""
    adapter = _adapter(
        _recent([("8-K", "not-a-date", "2.02"), ("8-K", "2025-02-01", "2.02")])
    )
    assert adapter.earnings_dates("AAPL", START, END) == (date(2025, 2, 1),)


def test_columns_of_unequal_length_are_truncated_rather_than_trusted() -> None:
    payload = {
        "filings": {
            "recent": {
                "form": ["8-K", "8-K"],
                "filingDate": ["2025-02-01"],
                "items": ["2.02", "2.02"],
            },
            "files": [],
        }
    }
    adapter = _adapter(lambda request: httpx.Response(200, json=payload))
    assert adapter.earnings_dates("AAPL", START, END) == (date(2025, 2, 1),)


def test_a_missing_filings_key_yields_no_dates() -> None:
    adapter = _adapter(lambda request: httpx.Response(200, json={}))
    assert adapter.earnings_dates("AAPL", START, END) == ()


def test_malformed_json_becomes_a_filings_error() -> None:
    adapter = _adapter(lambda request: httpx.Response(200, content=b"<html>not json</html>"))
    with pytest.raises(FilingsError, match="malformed JSON"):
        adapter.earnings_dates("AAPL", START, END)


def test_a_non_dict_submissions_block_is_ignored() -> None:
    payload = {"filings": {"recent": ["unexpected"], "files": []}}
    adapter = _adapter(lambda request: httpx.Response(200, json=payload))
    assert adapter.earnings_dates("AAPL", START, END) == ()


def test_a_non_dict_archive_entry_is_skipped() -> None:
    payload = {"filings": {"recent": _block([]), "files": ["not-an-object"]}}
    adapter = _adapter(lambda request: httpx.Response(200, json=payload))
    assert adapter.earnings_dates("AAPL", START, END) == ()
