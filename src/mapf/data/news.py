"""Loading untrusted news from a local directory and from RSS.

This is the first place raw feed text formally enters the system, so two rules
from ADR 0005 apply literally here and nowhere upstream.

**The id hashes the bytes as fetched, before any decoding.** That keeps
`source_doc_ids` an honest record of what arrived rather than of what we made of
it. Text is never mutated on the way in; quarantine happens later, at render time.

**One honest deviation, for RSS.** A feed is a single HTTP body carrying many
documents, and `feedparser` has already decoded and sanitised the markup by the
time we see an entry — there are no per-entry bytes off the wire to hash. Entry
ids therefore hash a canonical serialisation of the fields we actually use. The
feed's own bytes are hashed too and recorded alongside, so the fetch remains
verifiable even though the per-entry id is one step removed from it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

import httpx
import structlog

from mapf.core.errors import NewsSourceUnavailableError
from mapf.core.hashing import canonical_json, document_id
from mapf.core.models import Document, UntrustedText

_logger = structlog.get_logger(__name__)

TEXT_SUFFIXES = (".txt", ".md")


def _now() -> datetime:
    return datetime.now(UTC)


def load_directory(
    directory: Path,
    *,
    now: Callable[[], datetime] = _now,
) -> tuple[Document, ...]:
    """Read every `.txt`/`.md` file, hashing raw bytes.

    A missing directory is empty rather than an error: a corpus is optional, and
    `map run` should fail on "no material facts" with a clear message rather than
    on a path that was never created.
    """
    if not directory.is_dir():
        return ()

    fetched_at = now()
    documents: list[Document] = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            raw = path.read_bytes()
        except OSError as err:
            raise NewsSourceUnavailableError(str(path), str(err)) from err
        if not raw.strip():
            continue
        documents.append(
            Document(
                id=document_id(raw),
                source=str(path),
                # `errors="replace"` rather than a hard failure: one bad byte in a
                # scraped article should not lose the whole corpus, and the id
                # still records exactly what arrived.
                text=UntrustedText(raw.decode("utf-8", errors="replace")),
                fetched_at=fetched_at,
            )
        )
    return tuple(documents)


def _entry_bytes(entry: object) -> bytes:
    getter = getattr(entry, "get", None)
    fields = {}
    if callable(getter):
        for key in ("id", "link", "title", "published", "summary"):
            value = getter(key)
            if value:
                fields[key] = str(value)
    return canonical_json(fields).encode("utf-8")


def _entry_text(entry: object) -> str:
    getter = getattr(entry, "get", None)
    if not callable(getter):
        return ""
    parts = [str(getter(key) or "").strip() for key in ("title", "summary")]
    return "\n\n".join(part for part in parts if part)


def load_feed(
    url: str,
    *,
    client: httpx.Client,
    now: Callable[[], datetime] = _now,
) -> tuple[Document, ...]:
    """Fetch and parse one feed. Malformed feeds yield what they can."""
    import feedparser

    try:
        response = client.get(url, headers={"Accept": "application/rss+xml, application/xml"})
        response.raise_for_status()
    except httpx.HTTPError as err:
        raise NewsSourceUnavailableError(url, f"{type(err).__name__}: {err}") from err

    raw = response.content
    parsed = feedparser.parse(raw)
    if getattr(parsed, "bozo", 0) and not parsed.entries:
        raise NewsSourceUnavailableError(
            url, f"unparseable feed: {getattr(parsed, 'bozo_exception', 'unknown')}"
        )
    if getattr(parsed, "bozo", 0):
        # Real-world feeds are frequently malformed but still usable. Recovering
        # silently would hide a source degrading; refusing outright would discard
        # a usable corpus.
        _logger.warning("feed_malformed_but_usable", url=url, entries=len(parsed.entries))

    feed_digest = document_id(raw)
    fetched_at = now()
    documents: list[Document] = []
    for entry in parsed.entries:
        text = _entry_text(entry)
        if not text.strip():
            continue
        documents.append(
            Document(
                id=document_id(_entry_bytes(entry)),
                source=str(getattr(entry, "link", "") or url),
                text=UntrustedText(text),
                fetched_at=fetched_at,
            )
        )
    _logger.info("feed_loaded", url=url, entries=len(documents), feed_digest=feed_digest)
    return tuple(documents)


def load_corpus(
    directory: Path,
    rss_urls: Sequence[str] = (),
    *,
    client: httpx.Client | None = None,
    now: Callable[[], datetime] = _now,
) -> tuple[Document, ...]:
    """Local directory plus optional feeds, de-duplicated by document id."""
    documents = list(load_directory(directory, now=now))
    if rss_urls:
        if client is None:
            raise ValueError("an httpx.Client is required to load RSS feeds")
        for url in rss_urls:
            documents.extend(load_feed(url, client=client, now=now))

    seen: set[str] = set()
    unique: list[Document] = []
    for document in documents:
        if document.id in seen:
            continue
        seen.add(document.id)
        unique.append(document)
    return tuple(unique)
