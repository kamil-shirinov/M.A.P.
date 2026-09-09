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


def _accession(filed: str, index: int) -> str:
    """Unique per row and per block, so a fixture never makes two filings look
    like one. Tolerates the deliberately malformed dates used below."""
    digits = "".join(c for c in filed if c.isdigit()) or "0"
    return f"0000320193-26-{(int(digits) + index) % 1_000_000:06d}"


def _block(rows: list[tuple[str, str, str]]) -> dict[str, list[str]]:
    return {
        "form": [r[0] for r in rows],
        "filingDate": [r[1] for r in rows],
        "items": [r[2] for r in rows],
        # Unique per row *and* per block, so a fixture never accidentally makes two
        # different filings look like one.
        "accessionNumber": [_accession(r[1], i) for i, r in enumerate(rows)],
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
    adapter = _adapter(_recent([("10-Q", "2025-02-01", "2.02"), ("8-K", "2025-03-01", "2.02")]))
    assert adapter.earnings_dates("AAPL", START, END) == (date(2025, 3, 1),)


def test_item_2_02_is_matched_exactly_not_as_a_substring() -> None:
    """`12.02` and `2.021` must not match. A substring test would accept both."""
    adapter = _adapter(_recent([("8-K", "2025-02-01", "12.02"), ("8-K", "2025-03-01", "2.02")]))
    assert adapter.earnings_dates("AAPL", START, END) == (date(2025, 3, 1),)


def test_whitespace_around_items_is_tolerated() -> None:
    adapter = _adapter(_recent([("8-K", "2025-02-01", "9.01, 2.02 ")]))
    assert adapter.earnings_dates("AAPL", START, END) == (date(2025, 2, 1),)


# ---------------------------------------------------------------------------
# Window and ordering
# ---------------------------------------------------------------------------
def test_filings_outside_the_window_are_dropped() -> None:
    adapter = _adapter(_recent([("8-K", "2019-02-01", "2.02"), ("8-K", "2025-02-01", "2.02")]))
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
    adapter = _adapter(_recent([("8-K", "not-a-date", "2.02"), ("8-K", "2025-02-01", "2.02")]))
    assert adapter.earnings_dates("AAPL", START, END) == (date(2025, 2, 1),)


def test_columns_of_unequal_length_are_truncated_rather_than_trusted() -> None:
    payload = {
        "filings": {
            "recent": {
                "form": ["8-K", "8-K"],
                "filingDate": ["2025-02-01"],
                "items": ["2.02", "2.02"],
                "accessionNumber": ["0000320193-26-000001", "0000320193-26-000002"],
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


# ---------------------------------------------------------------------------
# Accession numbers — what makes an item reproducible
# ---------------------------------------------------------------------------
def test_filings_carry_accession_numbers() -> None:
    adapter = _adapter(_recent([("8-K", "2025-02-01", "2.02")]))
    filings = adapter.earnings_filings("AAPL", START, END)
    assert filings[0].accession == _accession("2025-02-01", 0)
    assert filings[0].cik == 320193
    assert filings[0].filed == date(2025, 2, 1)


def test_the_archive_path_segment_strips_dashes() -> None:
    """EDGAR's archive directories are the accession without punctuation."""
    adapter = _adapter(_recent([("8-K", "2025-02-01", "2.02")]))
    segment = adapter.earnings_filings("AAPL", START, END)[0].path_segment
    assert segment == _accession("2025-02-01", 0).replace("-", "")


def test_two_filings_on_one_day_stay_distinct() -> None:
    """A date alone cannot identify a filing; an accession can."""
    adapter = _adapter(_recent([("8-K", "2025-02-01", "2.02"), ("8-K", "2025-02-01", "2.02")]))
    filings = adapter.earnings_filings("AAPL", START, END)
    assert len({f.accession for f in filings}) == 2
    # The date-only view still collapses them, which is why it is not the identifier.
    assert adapter.earnings_dates("AAPL", START, END) == (date(2025, 2, 1),)


def test_a_malformed_accession_drops_only_that_row() -> None:
    payload = {
        "filings": {
            "recent": {
                "form": ["8-K", "8-K"],
                "filingDate": ["2025-02-01", "2025-03-01"],
                "items": ["2.02", "2.02"],
                "accessionNumber": ["not-an-accession", "0000320193-26-000012"],
            },
            "files": [],
        }
    }
    adapter = _adapter(lambda request: httpx.Response(200, json=payload))
    filings = adapter.earnings_filings("AAPL", START, END)
    assert [f.filed for f in filings] == [date(2025, 3, 1)]


# ---------------------------------------------------------------------------
# The by-CIK pre-screen read
# ---------------------------------------------------------------------------
def test_the_recent_block_is_read_by_cik_in_one_request() -> None:
    """Submissions are addressed by CIK. The index holds 10,398 tickers over 7,998
    filers, so a walk keyed on tickers fetches 2,400 identical documents."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(
            200,
            json={
                "filings": {
                    "recent": _block(
                        [
                            ("8-K", "2026-07-30", "2.02,9.01"),
                            ("8-K", "2026-04-30", "5.02"),
                            ("10-Q", "2026-04-30", ""),
                        ]
                    ),
                    "files": [{"name": "CIK0000320193-submissions-001.json"}],
                }
            },
        )

    found = _adapter(handler).recent_earnings_filings(320193)

    assert [f.filed for f in found] == [date(2026, 7, 30)]
    assert seen == ["https://data.sec.gov/submissions/CIK0000320193.json"]


def test_the_archives_are_never_walked_for_the_pre_screen() -> None:
    """One request per filer, fixed. Walking `files` is unbounded per filer and
    answers a question the pre-screen does not ask."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(
            200,
            json={
                "filings": {
                    "recent": _block([("10-K", "2026-02-01", "")]),
                    "files": [
                        {"name": "a.json", "filingFrom": "1994-01-01", "filingTo": "2010-01-01"}
                    ],
                }
            },
        )

    assert _adapter(handler).recent_earnings_filings(320193) == ()
    assert len(seen) == 1


def test_a_filer_with_no_recent_block_is_empty_not_an_error() -> None:
    """A shell, a new registrant, or a filer whose submissions carry no `recent`.
    Empty is the honest pre-screen answer; raising would halt a 7,998-filer walk
    on a document that is merely uninteresting."""
    handler = lambda request: httpx.Response(200, json={"filings": {}})  # noqa: E731

    assert _adapter(handler).recent_earnings_filings(1) == ()


def test_a_submissions_document_with_no_filings_key_is_empty() -> None:
    handler = lambda request: httpx.Response(200, json={"cik": "320193"})  # noqa: E731

    assert _adapter(handler).recent_earnings_filings(320193) == ()


def test_a_filings_value_that_is_not_an_object_is_empty() -> None:
    handler = lambda request: httpx.Response(200, json={"filings": []})  # noqa: E731

    assert _adapter(handler).recent_earnings_filings(320193) == ()
