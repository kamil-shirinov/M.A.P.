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

from mapf.core.errors import MapError
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
        symbol = self._symbols.get(ticker)
        if symbol is None or symbol.cik is None:
            raise UnknownFilerError(f"no CIK for {ticker!r}; it is not in the SEC index")

        document = self._fetch(SUBMISSIONS_URL.format(cik=symbol.cik))
        filings = document.get("filings", {})
        found = list(_earnings_dates(filings.get("recent", {})))
        earliest = min(found) if found else None

        # Only reach for the archives when `recent` genuinely does not cover the
        # window. For a large-cap filer it usually does.
        if earliest is None or earliest > start:
            for archive in filings.get("files", []) or []:
                if not isinstance(archive, dict):
                    continue
                name = archive.get("name")
                if not name or not _overlaps(archive, start, end):
                    continue
                found.extend(_earnings_dates(self._fetch(ARCHIVE_URL.format(name=name))))

        inside = sorted({d for d in found if start <= d <= end})
        _logger.debug(
            "edgar_earnings_dates",
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


def _earnings_dates(block: Any) -> tuple[date, ...]:
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
    out: list[date] = []
    for form, filed, item_list in zip(forms, dates, items, strict=False):
        if form != FORM_8K:
            continue
        if EARNINGS_ITEM not in {part.strip() for part in str(item_list).split(",")}:
            continue
        try:
            out.append(date.fromisoformat(str(filed)))
        except ValueError:  # noqa: PERF203 - a malformed date must not kill the ticker
            _logger.warning("edgar_unparseable_filing_date", value=filed)
    return tuple(out)


def _overlaps(archive: dict[str, Any], start: date, end: date) -> bool:
    """Whether an archive file's advertised range touches the window."""
    try:
        first = date.fromisoformat(str(archive.get("filingFrom", "")))
        last = date.fromisoformat(str(archive.get("filingTo", "")))
    except ValueError:
        return True  # Undated archive: fetch it rather than silently skip a window.
    return first <= end and last >= start
