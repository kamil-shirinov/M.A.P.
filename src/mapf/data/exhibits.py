"""Exhibit 99.1 — the earnings press release, and the corpus's actual input.

An Item 2.02 8-K body is usually a two-paragraph cover page that points at an
exhibit; the numbers live in EX-99.1. Fetching the body instead would feed the
pipeline a document containing no financial content at all, and it would look like
a working corpus.

Availability was never a selection criterion, so it has to be established before
the run rather than discovered on night three. A filing with no EX-99.1 is a
**terminal** condition: it will be missing on every resume, so retrying it would
consume the failure threshold afresh each pass.

HTML is reduced to text with `html.parser` from the standard library. No parsing
dependency is added for this: an earnings release is flat prose in tables, the
requirement is "drop tags and scripts, keep the words", and a dependency taken for
one adapter is a dependency the whole project then carries.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from html import unescape
from html.parser import HTMLParser

import httpx
import structlog

from mapf.core.errors import ExhibitError, MissingExhibitError
from mapf.core.hashing import document_id
from mapf.core.models import Document, EarningsFiling, UntrustedText
from mapf.data.symbols import Throttle

_logger = structlog.get_logger(__name__)

# The SGML submission header, which is the only machine-readable place the EDGAR
# *document type* appears. `index.json` looks like the obvious source and is not:
# its `type` field is the directory-listing icon name ("text.gif"), so matching it
# against "EX-99.1" never succeeds — and fails identically for every filing, which
# reads as universal attrition rather than as a bug.
HEADERS_URL = (
    "https://www.sec.gov/Archives/edgar/data/{cik}/{segment}/{accession}-index-headers.html"
)
DOCUMENT_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{segment}/{name}"

# EX-99.1 is the convention; EX-99 without a suffix is common enough on older
# filings to accept. Anything further out is a different exhibit entirely.
EXHIBIT_TYPES = ("EX-99.1", "EX-99")
# Tags arrive HTML-escaped inside the header page, so it is unescaped before this
# runs. One <DOCUMENT> block per filed document.
_DOCUMENT_RE = re.compile(r"<TYPE>(?P<type>[^\n<]+).*?<FILENAME>(?P<name>[^\n<]+)", re.DOTALL)
_SKIP_TAGS = frozenset({"script", "style", "head"})
MIN_EXHIBIT_CHARS = 200


__all__ = [
    "EdgarExhibits",
    "ExhibitError",
    "MissingExhibitError",
    "find_exhibit",
    "html_to_text",
]


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip and data.strip():
            self.parts.append(data.strip())


def html_to_text(raw: bytes) -> str:
    """Tags and scripts out, words kept, whitespace collapsed."""
    parser = _TextExtractor()
    parser.feed(unescape(raw.decode("utf-8", errors="replace")))
    parser.close()
    return "\n".join(parser.parts)


class EdgarExhibits:
    """Fetches EX-99.1 for a filing and returns it as an untrusted `Document`."""

    def __init__(self, *, user_agent: str, client: httpx.Client, throttle: Throttle) -> None:
        self._user_agent = user_agent
        self._client = client
        self._throttle = throttle

    def fetch(self, filing: EarningsFiling) -> Document:
        headers = self._get(
            HEADERS_URL.format(
                cik=filing.cik,
                segment=filing.path_segment,
                accession=filing.accession,
            )
        ).text
        name = find_exhibit(headers)
        if name is None:
            raise MissingExhibitError(
                f"{filing.accession} carries no {'/'.join(EXHIBIT_TYPES)} exhibit"
            )

        url = DOCUMENT_URL.format(cik=filing.cik, segment=filing.path_segment, name=name)
        raw = self._get(url).content
        text = (
            html_to_text(raw)
            if name.lower().endswith((".htm", ".html"))
            else (raw.decode("utf-8", errors="replace"))
        )
        if len(text.strip()) < MIN_EXHIBIT_CHARS:
            # A cover page or a stub graphic. Feeding it on would produce a
            # forecast from no financial content that looks like a real one.
            raise MissingExhibitError(
                f"{filing.accession} exhibit {name} held {len(text.strip())} characters"
            )

        _logger.debug("exhibit_fetched", accession=filing.accession, name=name, chars=len(text))
        # The id hashes the bytes as they arrived (ADR 0005), so it identifies the
        # exhibit rather than our rendering of it.
        return Document(
            id=document_id(raw),
            source=url,
            text=UntrustedText(text),
            fetched_at=datetime.now(UTC),
        )

    def _get(self, url: str) -> httpx.Response:
        self._throttle.wait()
        try:
            response = self._client.get(
                url, headers={"User-Agent": self._user_agent, "Accept-Encoding": "gzip"}
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise ExhibitError(f"EDGAR request failed for {url}: {error}") from error
        return response


def find_exhibit(headers: str) -> str | None:
    """The exhibit filename, preferring EX-99.1 over a bare EX-99."""
    by_type: dict[str, str] = {}
    for match in _DOCUMENT_RE.finditer(unescape(headers)):
        kind = match.group("type").strip().upper()
        if kind in EXHIBIT_TYPES:
            by_type.setdefault(kind, match.group("name").strip())
    for kind in EXHIBIT_TYPES:
        if kind in by_type:
            return by_type[kind]
    return None
