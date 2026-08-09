"""One derivation of the request key, shared by the cache and the fake.

Both need to answer "have I seen this exact request before?", and they must
answer it identically — a fixture recorded under one derivation and looked up
under another is a silent, permanent miss. So the derivation lives here and
neither module reimplements it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mapf.core.hashing import cache_key, canonical_json
from mapf.core.ports import ModelInfo, RenderedPrompt, SamplingParams


def request_key(
    *,
    model: ModelInfo,
    prompt: RenderedPrompt,
    sampling: SamplingParams,
    json_schema: Mapping[str, Any] | None = None,
    attempt: int = 0,
) -> str:
    """Derive the key for one completion request (ADR 0001).

    The decode schema is folded into the prompt component. ADR 0001 specifies
    fingerprint + prompt + sampling, and for a constrained call the grammar *is*
    part of the request: change the schema and the reachable token set changes, so
    the same messages can produce different output. Leaving it out would let a
    schema edit serve output shaped by the previous grammar — a false hit, which
    is the expensive direction.
    """
    prompt_payload = canonical_json(
        {
            "messages": [message.model_dump() for message in prompt.messages],
            "json_schema": dict(json_schema) if json_schema is not None else None,
        }
    )
    return cache_key(
        model_fingerprint=model.fingerprint,
        prompt=prompt_payload,
        sampling=sampling.model_dump(),
        attempt=attempt,
    )
