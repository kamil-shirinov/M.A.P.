"""The symbol index: SEC parsing, explicit sync, and offline search."""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

import httpx
import pytest

from mapf.core.errors import SymbolIndexMissingError
from mapf.data.symbols import (
    SqliteSymbolIndex,
    Throttle,
    parse_sec_tickers,
    sync,
)

FIXTURE = Path(__file__).parents[1] / "fixtures" / "sec" / "company_tickers_exchange.json"
URL = "https://www.sec.gov/files/company_tickers_exchange.json"
UA = "Jane Doe jane@example.com M.A.P. research tool"


def _client(body: bytes, status: int = 200, seen: dict[str, str] | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.update({k.lower(): v for k, v in request.headers.items()})
        return httpx.Response(status, content=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


def _index(tmp_path: Path, *, seen: dict[str, str] | None = None) -> SqliteSymbolIndex:
    db = tmp_path / "symbols.sqlite"
    sync(
        db,
        url=URL,
        user_agent=UA,
        client=_client(FIXTURE.read_bytes(), seen=seen),
        throttle=Throttle(8.0, sleep=lambda _: None),
        today=lambda: date(2026, 8, 11),
    )
    return SqliteSymbolIndex(db)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def test_the_column_oriented_file_is_read_by_field_name() -> None:
    """The payload is a `fields` list plus a `data` matrix. Reading positionally
    would silently swap ticker and name if the SEC reordered them."""
    symbols = parse_sec_tickers(FIXTURE.read_bytes())
    apple = next(s for s in symbols if s.ticker == "AAPL")
    assert apple.name == "Apple Inc."
    assert apple.cik == 320193
    assert apple.exchange == "Nasdaq"


def test_blank_rows_are_dropped() -> None:
    assert all(s.ticker and s.name for s in parse_sec_tickers(FIXTURE.read_bytes()))


def test_a_missing_exchange_is_allowed() -> None:
    symbols = parse_sec_tickers(FIXTURE.read_bytes())
    assert next(s for s in symbols if s.ticker == "ACN").exchange is None


def test_a_reordered_file_is_still_read_correctly() -> None:
    payload = {
        "fields": ["ticker", "cik", "exchange", "name"],
        "data": [["AAPL", 320193, "Nasdaq", "Apple Inc."]],
    }
    (symbol,) = parse_sec_tickers(json.dumps(payload).encode())
    assert (symbol.ticker, symbol.name) == ("AAPL", "Apple Inc.")


def test_a_file_missing_a_required_column_is_rejected() -> None:
    payload = {"fields": ["cik", "name"], "data": [[1, "X"]]}
    with pytest.raises(ValueError, match="missing the 'ticker' column"):
        parse_sec_tickers(json.dumps(payload).encode())


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------
def test_sync_sends_the_configured_user_agent(tmp_path: Path) -> None:
    """Without it EDGAR returns 403 and blocks the IP for about ten minutes."""
    seen: dict[str, str] = {}
    _index(tmp_path, seen=seen)
    assert seen["user-agent"] == UA


def test_sync_records_how_many_symbols_it_wrote(tmp_path: Path) -> None:
    db = tmp_path / "symbols.sqlite"
    count = sync(
        db,
        url=URL,
        user_agent=UA,
        client=_client(FIXTURE.read_bytes()),
        throttle=Throttle(8.0, sleep=lambda _: None),
        today=lambda: date(2026, 8, 11),
    )
    assert count == 6


def test_sync_is_idempotent(tmp_path: Path) -> None:
    """Re-syncing replaces rather than accumulating; otherwise every sync would
    double the index."""
    db = tmp_path / "symbols.sqlite"
    for _ in range(2):
        sync(
            db,
            url=URL,
            user_agent=UA,
            client=_client(FIXTURE.read_bytes()),
            throttle=Throttle(8.0, sleep=lambda _: None),
            today=lambda: date(2026, 8, 11),
        )
    with sqlite3.connect(db) as connection:
        assert connection.execute("SELECT COUNT(*) FROM symbols").fetchone()[0] == 6


def test_sync_records_its_date(tmp_path: Path) -> None:
    assert _index(tmp_path).synced_on() == date(2026, 8, 11)


def test_the_throttle_spaces_requests() -> None:
    slept: list[float] = []
    clock = iter([0.0, 0.0, 0.05, 0.05])
    throttle = Throttle(10.0, sleep=slept.append)
    throttle.wait(now=lambda: next(clock))
    throttle.wait(now=lambda: next(clock))
    assert slept and slept[0] == pytest.approx(0.05, abs=1e-6)


def test_a_non_positive_rate_is_rejected() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        Throttle(0.0)


# ---------------------------------------------------------------------------
# Search — offline and pure
# ---------------------------------------------------------------------------
def test_search_finds_the_exact_ticker_first(tmp_path: Path) -> None:
    matches = _index(tmp_path).search("AAPL")
    assert matches[0].symbol.ticker == "AAPL"
    assert matches[0].score == 1.0


def test_search_by_name_returns_ranked_candidates(tmp_path: Path) -> None:
    """DoD criterion 2. Both Apples match; ambiguity is returned, not resolved."""
    tickers = [m.symbol.ticker for m in _index(tmp_path).search("apple")]
    assert "AAPL" in tickers
    assert "APLE" in tickers


def test_scores_are_ordinal_and_bounded(tmp_path: Path) -> None:
    matches = _index(tmp_path).search("apple")
    assert all(0.0 <= m.score <= 1.0 for m in matches)
    assert [m.score for m in matches] == sorted((m.score for m in matches), reverse=True)


def test_search_respects_the_limit(tmp_path: Path) -> None:
    assert len(_index(tmp_path).search("inc", limit=1)) <= 1


def test_a_query_with_fts_syntax_is_treated_as_text(tmp_path: Path) -> None:
    """A user searching for `AND` or a quote should get a search, not a parse
    error and not a wildcard they never asked for."""
    index = _index(tmp_path)
    assert index.search('apple" OR ') is not None
    assert index.search("AND") is not None


def test_an_unknown_query_returns_nothing(tmp_path: Path) -> None:
    assert _index(tmp_path).search("zzzznotacompany") == ()


def test_get_is_case_insensitive(tmp_path: Path) -> None:
    index = _index(tmp_path)
    assert index.get("aapl") is not None
    assert index.get("  aapl  ") is not None


def test_search_never_syncs(tmp_path: Path) -> None:
    """A search that silently downloads breaks the offline guarantee and turns an
    EDGAR 403 into a mysterious hang inside a local lookup."""
    with pytest.raises(SymbolIndexMissingError) as caught:
        SqliteSymbolIndex(tmp_path / "absent.sqlite").search("apple")
    assert "map symbols sync" in str(caught.value)


def test_get_also_fails_loudly_without_an_index(tmp_path: Path) -> None:
    with pytest.raises(SymbolIndexMissingError):
        SqliteSymbolIndex(tmp_path / "absent.sqlite").get("AAPL")


def test_the_index_can_be_enumerated(tmp_path: Path) -> None:
    assert len(list(_index(tmp_path))) == 6
