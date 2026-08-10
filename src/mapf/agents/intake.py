"""Agent 1 — compress source documents into material facts."""

from __future__ import annotations

from datetime import date

from pydantic import Field

from mapf.agents.base import LLMAgent
from mapf.core.errors import NoMaterialFactsError
from mapf.core.models import (
    Document,
    DocumentId,
    DomainModel,
    MaterialFacts,
    Ticker,
    TrustedText,
    UntrustedText,
)
from mapf.core.quarantine import quarantine

TEMPLATE = "intake"
VERSION = "v1"

_BULLETS = ("- ", "* ", "• ")


class IntakeRequest(DomainModel):
    ticker: Ticker
    # The price window's last trading date, never a wall clock. A timestamp here
    # would change the prompt on every run and make the cache useless (ADR 0001).
    as_of_date: date
    documents: tuple[Document, ...] = Field(min_length=1)


def _parse_facts(raw: str) -> tuple[str, ...]:
    """Bullets if the model produced them, otherwise every non-empty line.

    The fallback is pragmatic rather than principled: a 3B model asked for a bullet
    list sometimes returns bare lines, and discarding a correct answer over its
    formatting would be worse than the occasional stray line. The raw response is
    in the trace either way.
    """
    lines = [line.strip() for line in raw.splitlines()]
    bullets = [
        line[2:].strip()
        for line in lines
        if any(line.startswith(bullet) for bullet in _BULLETS) and line[2:].strip()
    ]
    if bullets:
        return tuple(bullets)
    return tuple(line for line in lines if line)


class IntakeAgent(LLMAgent):
    """`IntakeRequest -> MaterialFacts`."""

    def run(self, request: IntakeRequest, /) -> MaterialFacts:
        prompt = self._render(
            TEMPLATE,
            VERSION,
            trusted={
                "ticker": TrustedText(request.ticker),
                "as_of_date": TrustedText(request.as_of_date.isoformat()),
            },
            # The whole corpus is quarantined as one block. Per-document labels sit
            # inside it and are sanitised with everything else, so a document that
            # forges a label can confuse the boundary but cannot escape the block.
            untrusted={"documents": quarantine(_join(request.documents))},
        )
        response = self._complete(prompt)

        facts = _parse_facts(response.text)
        if not facts:
            raise NoMaterialFactsError(request.ticker, len(request.documents))

        return MaterialFacts(
            ticker=request.ticker,
            # Taint propagates: this is model output derived from feed text, and it
            # is interpolated into Agent 2's prompt (ADR 0005).
            facts=tuple(UntrustedText(fact) for fact in facts),
            source_doc_ids=tuple(DocumentId(document.id) for document in request.documents),
        )


def _join(documents: tuple[Document, ...]) -> str:
    total = len(documents)
    return "\n\n".join(
        f"[document {index} of {total} | source: {document.source}]\n{document.text}"
        for index, document in enumerate(documents, start=1)
    )
