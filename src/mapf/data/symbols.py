"""The local symbol universe: SEC download, SQLite FTS5, offline search.

**Sync is an explicit command; search never triggers it.** A search that silently
downloads breaks the offline guarantee this project makes, and turns an EDGAR 403
— which blocks the IP for about ten minutes — into a mysterious hang inside what
looked like a local lookup. When the index is absent, search fails and names the
command that builds it.

Coverage is **US-listed companies only**, by construction: the source is the SEC's
own ticker file. Suffixed non-US tickers work if you already know them; they never
appear in name search, and the README says so.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import closing
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import structlog

from mapf.core.errors import SymbolIndexMissingError
from mapf.core.models import Symbol, SymbolMatch
from mapf.data.sec import require_usable_user_agent

_logger = structlog.get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS symbols (
    ticker   TEXT PRIMARY KEY,
    name     TEXT NOT NULL,
    exchange TEXT,
    cik      INTEGER
);
CREATE VIRTUAL TABLE IF NOT EXISTS symbols_fts
    USING fts5(ticker, name, content='symbols', content_rowid='rowid');
CREATE TABLE IF NOT EXISTS sync_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Throttle:
    """Spaces requests to stay under EDGAR's published ceiling.

    Injectable sleeper so tests never actually wait — a throttle that forces the
    suite to sleep is a throttle that gets deleted.
    """

    def __init__(self, requests_per_second: float, *, sleep: Callable[[float], None] = time.sleep):
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be positive")
        self._interval = 1.0 / requests_per_second
        self._sleep = sleep
        self._last: float | None = None

    def wait(self, *, now: Callable[[], float] = time.monotonic) -> None:
        current = now()
        if self._last is not None:
            remaining = self._interval - (current - self._last)
            if remaining > 0:
                self._sleep(remaining)
        self._last = now()


def parse_sec_tickers(raw: bytes) -> tuple[Symbol, ...]:
    """Parse `company_tickers_exchange.json`.

    The file is column-oriented — a `fields` list plus a `data` matrix — so the
    field names are read from the payload rather than assumed positionally. A
    reordering upstream would otherwise silently swap ticker and name.
    """
    payload = json.loads(raw)
    fields = [str(field).lower() for field in payload["fields"]]
    index = {name: position for position, name in enumerate(fields)}
    for required in ("cik", "name", "ticker"):
        if required not in index:
            raise ValueError(f"SEC ticker file is missing the {required!r} column: {fields}")

    symbols: list[Symbol] = []
    for row in payload["data"]:
        ticker = str(row[index["ticker"]] or "").strip()
        name = str(row[index["name"]] or "").strip()
        if not ticker or not name:
            continue
        exchange = row[index["exchange"]] if "exchange" in index else None
        symbols.append(
            Symbol(
                ticker=ticker,
                name=name,
                exchange=str(exchange) if exchange else None,
                cik=int(row[index["cik"]]) or None,
            )
        )
    return tuple(symbols)


def fetch_sec_tickers(
    url: str,
    *,
    user_agent: str,
    client: httpx.Client,
    throttle: Throttle,
) -> bytes:
    """Download the ticker file with the configured User-Agent.

    EDGAR answers a request without a descriptive User-Agent with 403 and blocks
    the IP for roughly ten minutes, so the header is not optional and is never
    defaulted in code — it comes from configuration, which validates it at startup.
    """
    throttle.wait()
    agent = require_usable_user_agent(user_agent)
    response = client.get(url, headers={"User-Agent": agent, "Accept-Encoding": "gzip"})
    response.raise_for_status()
    return response.content


def sync(
    db_path: Path,
    *,
    url: str,
    user_agent: str,
    client: httpx.Client,
    throttle: Throttle,
    today: Callable[[], date] = lambda: datetime.now(UTC).date(),
) -> int:
    """Rebuild the index. Explicit, never a side effect of searching."""
    symbols = parse_sec_tickers(
        fetch_sec_tickers(url, user_agent=user_agent, client=client, throttle=throttle)
    )
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db_path)) as connection:
        connection.executescript(_SCHEMA)
        connection.execute("DELETE FROM symbols")
        connection.execute("DELETE FROM symbols_fts")
        connection.executemany(
            "INSERT OR REPLACE INTO symbols (ticker, name, exchange, cik) VALUES (?, ?, ?, ?)",
            [(s.ticker, s.name, s.exchange, s.cik) for s in symbols],
        )
        connection.execute(
            "INSERT INTO symbols_fts (rowid, ticker, name) SELECT rowid, ticker, name FROM symbols"
        )
        connection.execute(
            "INSERT OR REPLACE INTO sync_meta (key, value) VALUES ('synced_on', ?)",
            (today().isoformat(),),
        )
        connection.commit()
    _logger.info("symbol_index_synced", symbols=len(symbols), path=str(db_path))
    return len(symbols)


def _escape_fts(query: str) -> str:
    """Quote the query so FTS5 treats it as text rather than syntax.

    A user searching for `AND` or `a*b` should get a search, not a parse error or
    a wildcard they did not ask for.
    """
    cleaned = query.replace('"', " ").strip()
    tokens = [token for token in cleaned.split() if token]
    return " ".join(f'"{token}"' for token in tokens)


class SqliteSymbolIndex:
    """A `SymbolIndex` over the synced database. Reads only; never fetches."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def synced_on(self) -> date | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM sync_meta WHERE key = 'synced_on'"
            ).fetchone()
        return date.fromisoformat(row[0]) if row else None

    def _connect(self) -> sqlite3.Connection:
        if not self._db_path.is_file():
            raise SymbolIndexMissingError(str(self._db_path))
        return sqlite3.connect(f"file:{self._db_path}?mode=ro", uri=True)

    def get(self, ticker: str) -> Symbol | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT ticker, name, exchange, cik FROM symbols WHERE ticker = ?",
                (ticker.strip().upper(),),
            ).fetchone()
        return _to_symbol(row) if row else None

    def search(self, query: str, *, limit: int = 10) -> Sequence[SymbolMatch]:
        """Ranked candidates. Never resolves ambiguity on the caller's behalf.

        The score is **ordinal, not probabilistic** — an exact ticker hit is 1.0
        and everything else is ranked by FTS5's own relevance. It says which
        candidate is best, not how likely any of them is to be right.
        """
        exact = self.get(query)
        matches: list[SymbolMatch] = []
        seen: set[str] = set()
        if exact is not None:
            matches.append(SymbolMatch(symbol=exact, score=1.0))
            seen.add(exact.ticker)

        expression = _escape_fts(query)
        if expression:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT s.ticker, s.name, s.exchange, s.cik FROM symbols_fts f "
                    "JOIN symbols s ON s.rowid = f.rowid "
                    "WHERE symbols_fts MATCH ? ORDER BY bm25(symbols_fts) LIMIT ?",
                    (expression, limit * 2),
                ).fetchall()
            for position, row in enumerate(rows):
                symbol = _to_symbol(row)
                if symbol.ticker in seen:
                    continue
                seen.add(symbol.ticker)
                matches.append(SymbolMatch(symbol=symbol, score=round(1.0 / (2.0 + position), 4)))

        return tuple(matches[:limit])

    def __iter__(self) -> Iterator[Symbol]:
        with self._connect() as connection:
            for row in connection.execute("SELECT ticker, name, exchange, cik FROM symbols"):
                yield _to_symbol(row)


def _to_symbol(row: tuple[str, str, str | None, int | None]) -> Symbol:
    return Symbol(ticker=row[0], name=row[1], exchange=row[2], cik=row[3])
