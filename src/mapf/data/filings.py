"""Item 2.02 filing dates from SEC EDGAR.

Item 2.02 is "Results of Operations and Financial Condition" — the quarterly
earnings release. Filtering to it is the whole point of this adapter, and the
reason is arithmetic: an 8-K count across *all* item types runs 8–12 a year and
suggests a panel that cannot actually be built, while Item 2.02 is four a year at
most (ADR 0018). A forecast window that opens on a 5.02 director departure is not
the same object as one that opens on an earnings release, and mixing them would
change what "calibrated" means without changing anything visible.

EDGAR serves a submissions document per CIK. The most recent filings live inline
under `filings.recent`; older ones are paginated into archive files listed under
`filings.files`. The archives are fetched only when `recent` does not reach back far
enough, because for a large-cap filer `recent` typically covers several years and
the extra request is pure cost.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import httpx
import structlog
from pydantic import ValidationError

from mapf.core.errors import MapError
from mapf.core.models import EarningsFiling
from mapf.core.ports import SymbolIndex
from mapf.data.symbols import Throttle

_logger = structlog.get_logger(__name__)

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
ARCHIVE_URL = "https://data.sec.gov/submissions/{name}"
EARNINGS_ITEM = "2.02"
FORM_8K = "8-K"


class FilingsError(MapError):
    """EDGAR could not be read for a ticker."""


class UnknownFilerError(FilingsError):
    """No CIK for the ticker, so EDGAR cannot be addressed at all.

    Distinct from "filed nothing": an unknown filer is a selection-time rejection
    with a reason, whereas an empty result is a legitimate answer.
    """


class EdgarFilings:
    """`FilingSource` over EDGAR submissions.

    The User-Agent is mandatory and never defaulted in code: EDGAR answers a
    request without a descriptive one with 403 and blocks the IP for roughly ten
    minutes. It comes from configuration, which validates it at startup.
    """

    def __init__(
        self,
        symbols: SymbolIndex,
        *,
        user_agent: str,
        client: httpx.Client,
        throttle: Throttle,
    ) -> None:
        self._symbols = symbols
        self._user_agent = user_agent
        self._client = client
        self._throttle = throttle

    def earnings_dates(self, ticker: str, start: date, end: date) -> tuple[date, ...]:
        # Distinct dates: selection counts forecast windows, and two filings on
        # one day are one window. `earnings_filings` keeps them separate.
        return tuple(sorted({f.filed for f in self.earnings_filings(ticker, start, end)}))

    def earnings_filings(self, ticker: str, start: date, end: date) -> tuple[EarningsFiling, ...]:
        """Filings with their accession numbers.

        Selection only needs dates, but the corpus needs identifiers: a ticker and
        a date very nearly resolve to one filing, and an 8-K/A amendment or two
        same-day filings are exactly where "very nearly" fails.
        """
        symbol = self._symbols.get(ticker)
        if symbol is None or symbol.cik is None:
            raise UnknownFilerError(f"no CIK for {ticker!r}; it is not in the SEC index")

        document = self._fetch(SUBMISSIONS_URL.format(cik=symbol.cik))
        filings = document.get("filings", {})
        found = list(_earnings_rows(filings.get("recent", {}), symbol.cik))
        earliest = min((f.filed for f in found), default=None)

        # Only reach for the archives when `recent` genuinely does not cover the
        # window. For a large-cap filer it usually does.
        if earliest is None or earliest > start:
            for archive in filings.get("files", []) or []:
                if not isinstance(archive, dict):
                    continue
                name = archive.get("name")
                if not name or not _overlaps(archive, start, end):
                    continue
                found.extend(_earnings_rows(self._fetch(ARCHIVE_URL.format(name=name)), symbol.cik))

        seen: dict[str, EarningsFiling] = {}
        for filing in found:
            if start <= filing.filed <= end:
                seen.setdefault(filing.accession, filing)
        inside = sorted(seen.values(), key=lambda f: (f.filed, f.accession))
        _logger.debug(
            "edgar_earnings_filings",
            ticker=ticker,
            cik=symbol.cik,
            found=len(inside),
            window=f"{start}..{end}",
        )
        return tuple(inside)

    def _fetch(self, url: str) -> dict[str, Any]:
        self._throttle.wait()
        try:
            response = self._client.get(
                url, headers={"User-Agent": self._user_agent, "Accept-Encoding": "gzip"}
            )
            response.raise_for_status()
            parsed: Any = response.json()
        except httpx.HTTPError as error:
            raise FilingsError(f"EDGAR request failed for {url}: {error}") from error
        except json.JSONDecodeError as error:
            raise FilingsError(f"EDGAR returned malformed JSON for {url}") from error
        if not isinstance(parsed, dict):
            raise FilingsError(f"EDGAR returned {type(parsed).__name__}, expected an object")
        return parsed


def _earnings_rows(block: Any, cik: int) -> tuple[EarningsFiling, ...]:
    """Pull Item 2.02 8-K dates out of one submissions block.

    EDGAR stores a submissions block column-wise — parallel arrays rather than a
    list of records — so the arrays are zipped back into rows here. A block whose
    columns disagree in length is truncated to the shortest rather than trusted.
    """
    if not isinstance(block, dict):
        return ()
    forms = block.get("form") or []
    dates = block.get("filingDate") or []
    items = block.get("items") or []
    accessions = block.get("accessionNumber") or []
    out: list[EarningsFiling] = []
    for form, filed, item_list, accession in zip(forms, dates, items, accessions, strict=False):
        if form != FORM_8K:
            continue
        if EARNINGS_ITEM not in {part.strip() for part in str(item_list).split(",")}:
            continue
        try:
            out.append(
                EarningsFiling(
                    accession=str(accession), cik=cik, filed=date.fromisoformat(str(filed))
                )
            )
        except (ValueError, ValidationError):  # noqa: PERF203 - one bad row must not kill the filer
            _logger.warning("edgar_unparseable_filing_row", value=filed, accession=accession)
    return tuple(out)


def _overlaps(archive: dict[str, Any], start: date, end: date) -> bool:
    """Whether an archive file's advertised range touches the window."""
    try:
        first = date.fromisoformat(str(archive.get("filingFrom", "")))
        last = date.fromisoformat(str(archive.get("filingTo", "")))
    except ValueError:
        return True  # Undated archive: fetch it rather than silently skip a window.
    return first <= end and last >= start
