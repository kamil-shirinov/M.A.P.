"""Identity and cache-key derivation.

Everything here is a pure function of its arguments, with one deliberate
exception: `new_run_id`. It is the only nondeterministic function in `core`, it
reads no clock (uuid4 is random, not time-based), and it lives here so that every
identifier the project mints is defined in one file.

The cache is load-bearing infrastructure, not an optimisation (`CLAUDE.md` §6):
on this hardware a 12B runs at 8-15 tok/s and a cold run pays three model swaps.
A key that is wrong in either direction is expensive — a false miss costs
minutes, a false hit silently serves another model's answer.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any
from uuid import UUID, uuid4

_ENCODING = "utf-8"


def canonical_json(value: Any) -> str:
    """Serialise so that equal inputs always produce equal bytes.

    `sort_keys` removes dict-ordering as a source of key churn: two calls with the
    same sampling parameters must hash identically regardless of how the mapping
    was built. `allow_nan=False` rejects NaN and Infinity outright — a NaN
    temperature is a bug, and letting it through would produce a key that never
    matches itself.
    """
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def sha256_hex(data: bytes) -> str:
    """Bare hex digest, no prefix."""
    return hashlib.sha256(data).hexdigest()


def document_id(raw: bytes) -> str:
    """Identify a document by the bytes exactly as they arrived (ADR 0005).

    Hashing raw bytes rather than decoded or normalised text is what keeps
    `source_doc_ids` an honest record of the source. The cost is that two
    documents differing only in line endings are distinct, which is correct but
    means a re-fetch that normalises whitespace will miss.
    """
    return f"sha256:{sha256_hex(raw)}"


def content_sha256(text: str) -> str:
    """Hash a prompt template's contents for the manifest."""
    return sha256_hex(text.encode(_ENCODING))


def cache_key(
    *,
    model_fingerprint: str,
    prompt: str,
    sampling: Mapping[str, Any],
    attempt: int = 0,
) -> str:
    """Derive the disk-cache key for one inference call.

    Keyed on the model *fingerprint*, never the tag: a registry can silently
    re-point a tag at different weights, and a tag-keyed cache would then serve
    the previous model's answers forever with nothing to surface it (ADR 0001).

    `attempt` distinguishes repair retries. The retry prompt already differs,
    because the validation errors are appended to it — but when the same errors
    recur, which is the common case, the third attempt would render identically
    to the second, hit this key, and replay a known failure without ever calling
    the model.

    The parts are hashed as one canonical JSON object rather than concatenated,
    so no combination of field values can be confused with another.
    """
    if attempt < 0:
        raise ValueError(f"attempt must be non-negative, got {attempt}")
    payload = {
        "model_fingerprint": model_fingerprint,
        "prompt": prompt,
        "sampling": dict(sampling),
        "attempt": attempt,
    }
    return sha256_hex(canonical_json(payload).encode(_ENCODING))


def new_run_id() -> UUID:
    """Mint a run identifier.

    uuid4 rather than a timestamp or a counter: a run id must be unique without
    consulting a clock or any prior state, so that `core` stays pure and two runs
    started in the same second cannot collide.
    """
    return uuid4()
