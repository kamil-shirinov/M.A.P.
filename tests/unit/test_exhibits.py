"""Exhibit 99.1 fetching.

The failure this module exists to prevent is silent: an Item 2.02 body is a
two-paragraph cover page, so fetching the wrong document yields a corpus of
forecasts made from no financial content, and every one of them validates.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import httpx
import pytest

from mapf.core.hashing import document_id
from mapf.core.models import EarningsFiling
from mapf.data.exhibits import (
    EdgarExhibits,
    ExhibitError,
    MissingExhibitError,
    html_to_text,
)
from mapf.data.symbols import Throttle

FILING = EarningsFiling(accession="0000320193-26-000012", cik=320193, filed=date(2026, 2, 1))
BODY = b"<html><body><p>" + b"Revenue rose to $124.3 billion. " * 20 + b"</p></body></html>"


def _index(items: list[dict[str, str]]) -> dict[str, object]:
    return {"directory": {"item": items}}


def _adapter(handler: Callable[[httpx.Request], httpx.Response]) -> EdgarExhibits:
    return EdgarExhibits(
        user_agent="Test test@example.com",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        throttle=Throttle(1000.0, sleep=lambda _: None),
    )


def _serving(
    items: list[dict[str, str]], body: bytes = BODY
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("index.json"):
            return httpx.Response(200, json=_index(items))
        return httpx.Response(200, content=body)

    return handler


# ---------------------------------------------------------------------------
# Finding the right document
# ---------------------------------------------------------------------------
def test_the_exhibit_is_fetched_not_the_8k_body() -> None:
    """The body is a cover page; the numbers are in EX-99.1."""
    adapter = _adapter(
        _serving(
            [
                {"name": "aapl-8k.htm", "type": "8-K"},
                {"name": "ex-991.htm", "type": "EX-99.1"},
            ]
        )
    )
    document = adapter.fetch(FILING)
    assert document.source.endswith("ex-991.htm")
    assert "Revenue rose" in document.text


def test_a_bare_ex_99_is_accepted_when_there_is_no_ex_99_1() -> None:
    adapter = _adapter(_serving([{"name": "ex99.htm", "type": "EX-99"}]))
    assert adapter.fetch(FILING).source.endswith("ex99.htm")


def test_ex_99_1_is_preferred_over_a_bare_ex_99() -> None:
    adapter = _adapter(
        _serving(
            [
                {"name": "ex99.htm", "type": "EX-99"},
                {"name": "ex-991.htm", "type": "EX-99.1"},
            ]
        )
    )
    assert adapter.fetch(FILING).source.endswith("ex-991.htm")


def test_a_filing_with_no_exhibit_raises_missing_not_generic() -> None:
    """Terminal, so the runner records it done rather than retrying every resume."""
    adapter = _adapter(_serving([{"name": "aapl-8k.htm", "type": "8-K"}]))
    with pytest.raises(MissingExhibitError, match="no EX-99"):
        adapter.fetch(FILING)


def test_a_stub_exhibit_is_rejected_as_missing() -> None:
    """A cover page or a logo would otherwise produce a forecast from nothing."""
    adapter = _adapter(
        _serving([{"name": "ex-991.htm", "type": "EX-99.1"}], b"<p>See attached.</p>")
    )
    with pytest.raises(MissingExhibitError, match="characters"):
        adapter.fetch(FILING)


def test_the_url_is_built_from_the_accession_without_dashes() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if str(request.url).endswith("index.json"):
            return httpx.Response(200, json=_index([{"name": "e.htm", "type": "EX-99.1"}]))
        return httpx.Response(200, content=BODY)

    _adapter(handler).fetch(FILING)
    assert all("000032019326000012" in url for url in seen)


# ---------------------------------------------------------------------------
# The document it produces
# ---------------------------------------------------------------------------
def test_the_document_id_hashes_the_bytes_as_they_arrived() -> None:
    """Hashing our rendering instead would make the id a record of our parser."""
    adapter = _adapter(_serving([{"name": "e.htm", "type": "EX-99.1"}]))
    assert adapter.fetch(FILING).id == document_id(BODY)


def test_a_plain_text_exhibit_is_not_html_stripped() -> None:
    adapter = _adapter(
        _serving([{"name": "e.txt", "type": "EX-99.1"}], b"Net income " + b"rose. " * 40)
    )
    assert "Net income" in adapter.fetch(FILING).text


# ---------------------------------------------------------------------------
# HTML reduction
# ---------------------------------------------------------------------------
def test_tags_are_dropped_and_words_kept() -> None:
    assert html_to_text(b"<p>Revenue <b>rose</b> 12%</p>") == "Revenue\nrose\n12%"


def test_script_and_style_contents_are_discarded() -> None:
    raw = b"<style>p{color:red}</style><script>var x=1</script><p>Real text</p>"
    assert html_to_text(raw) == "Real text"


def test_entities_are_decoded() -> None:
    assert html_to_text(b"<p>AT&amp;T beat by $0.05</p>") == "AT&T beat by $0.05"


def test_undecodable_bytes_do_not_raise() -> None:
    """One bad byte must not cost the filing."""
    assert "Revenue" in html_to_text(b"<p>Revenue \xff\xfe rose</p>")


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------
def test_an_http_error_is_an_exhibit_error_not_a_missing_exhibit() -> None:
    """Transient and terminal must not be confused: one retries, one does not."""
    adapter = _adapter(lambda request: httpx.Response(503))
    with pytest.raises(ExhibitError) as caught:
        adapter.fetch(FILING)
    assert not isinstance(caught.value, MissingExhibitError)


def test_a_malformed_index_reads_as_missing() -> None:
    adapter = _adapter(lambda request: httpx.Response(200, json={"unexpected": True}))
    with pytest.raises(MissingExhibitError):
        adapter.fetch(FILING)


def test_a_non_list_item_block_reads_as_missing() -> None:
    adapter = _adapter(
        lambda request: httpx.Response(200, json={"directory": {"item": "nope"}})
    )
    with pytest.raises(MissingExhibitError):
        adapter.fetch(FILING)


def test_a_non_dict_index_entry_is_skipped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("index.json"):
            return httpx.Response(
                200,
                json={"directory": {"item": ["junk", {"name": "e.htm", "type": "EX-99.1"}]}},
            )
        return httpx.Response(200, content=BODY)

    assert _adapter(handler).fetch(FILING).source.endswith("e.htm")


def test_an_index_entry_without_a_name_is_skipped() -> None:
    """A malformed entry must not be selected and then fetched as `None`."""
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("index.json"):
            return httpx.Response(
                200,
                json={"directory": {"item": [{"type": "EX-99.1"},
                                             {"name": "e.htm", "type": "EX-99.1"}]}},
            )
        return httpx.Response(200, content=BODY)

    assert _adapter(handler).fetch(FILING).source.endswith("e.htm")


def test_a_non_dict_index_document_reads_as_missing() -> None:
    adapter = _adapter(lambda request: httpx.Response(200, json=["not", "a", "dict"]))
    with pytest.raises(MissingExhibitError):
        adapter.fetch(FILING)
