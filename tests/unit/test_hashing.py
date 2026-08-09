"""Cache-key and identity derivation.

Two failure modes matter here and they are not symmetric. A **false miss** costs
minutes of recomputation. A **false hit** silently serves another model's answer
into a forecast that then looks entirely normal — which is why the fingerprint,
the attempt index and the sampling parameters are all in the key (ADR 0001).
"""

from __future__ import annotations

from uuid import UUID

import pytest

from mapf.core.hashing import cache_key, content_sha256, document_id, new_run_id, sha256_hex

SAMPLING = {"temperature": 0.0, "seed": 7, "max_tokens": 512}


# ---------------------------------------------------------------------------
# Document identity
# ---------------------------------------------------------------------------
def test_document_id_is_prefixed_and_64_hex_chars() -> None:
    doc_id = document_id(b"some news text")
    prefix, _, digest = doc_id.partition(":")
    assert prefix == "sha256"
    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")


def test_document_id_is_stable() -> None:
    assert document_id(b"same bytes") == document_id(b"same bytes")


def test_document_id_distinguishes_different_bytes() -> None:
    assert document_id(b"a") != document_id(b"b")


def test_document_id_hashes_raw_bytes_not_normalised_text() -> None:
    """ADR 0005: two documents differing only in line endings are distinct.

    That is the intended cost of an honest id — it records what arrived, not what
    we decided it meant.
    """
    assert document_id(b"line\r\n") != document_id(b"line\n")


# ---------------------------------------------------------------------------
# Cache keys
# ---------------------------------------------------------------------------
def test_cache_key_is_deterministic() -> None:
    first = cache_key(model_fingerprint="fp", prompt="p", sampling=SAMPLING)
    second = cache_key(model_fingerprint="fp", prompt="p", sampling=SAMPLING)
    assert first == second


def test_cache_key_ignores_sampling_dict_ordering() -> None:
    """Otherwise the key would depend on how the mapping happened to be built."""
    reordered = {"max_tokens": 512, "temperature": 0.0, "seed": 7}
    assert cache_key(model_fingerprint="fp", prompt="p", sampling=SAMPLING) == cache_key(
        model_fingerprint="fp", prompt="p", sampling=reordered
    )


def test_cache_key_changes_with_fingerprint() -> None:
    """The whole point: a re-pointed tag must not serve the old model's answers."""
    assert cache_key(model_fingerprint="fp1", prompt="p", sampling=SAMPLING) != cache_key(
        model_fingerprint="fp2", prompt="p", sampling=SAMPLING
    )


def test_cache_key_changes_with_prompt() -> None:
    assert cache_key(model_fingerprint="fp", prompt="a", sampling=SAMPLING) != cache_key(
        model_fingerprint="fp", prompt="b", sampling=SAMPLING
    )


def test_cache_key_changes_with_sampling() -> None:
    assert cache_key(model_fingerprint="fp", prompt="p", sampling=SAMPLING) != cache_key(
        model_fingerprint="fp", prompt="p", sampling={**SAMPLING, "temperature": 0.7}
    )


def test_cache_key_changes_with_attempt() -> None:
    """Without this, a repair retry whose errors recur replays its own failure
    from cache and burns the remaining budget without calling the model."""
    assert cache_key(model_fingerprint="fp", prompt="p", sampling=SAMPLING, attempt=1) != cache_key(
        model_fingerprint="fp", prompt="p", sampling=SAMPLING, attempt=2
    )


def test_cache_key_defaults_to_attempt_zero() -> None:
    assert cache_key(model_fingerprint="fp", prompt="p", sampling=SAMPLING) == cache_key(
        model_fingerprint="fp", prompt="p", sampling=SAMPLING, attempt=0
    )


def test_negative_attempt_is_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        cache_key(model_fingerprint="fp", prompt="p", sampling=SAMPLING, attempt=-1)


def test_nan_sampling_value_is_rejected() -> None:
    """A NaN temperature would produce a key that never matches itself."""
    with pytest.raises(ValueError, match="Out of range|NaN|not JSON compliant"):
        cache_key(model_fingerprint="fp", prompt="p", sampling={"temperature": float("nan")})


def test_fields_cannot_be_confused_by_concatenation() -> None:
    """Hashing a canonical JSON object rather than a joined string means no
    combination of values can impersonate another."""
    assert cache_key(model_fingerprint="ab", prompt="c", sampling={}) != cache_key(
        model_fingerprint="a", prompt="bc", sampling={}
    )


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------
def test_content_sha256_is_bare_hex() -> None:
    digest = content_sha256("template text")
    assert len(digest) == 64
    assert ":" not in digest


def test_sha256_hex_matches_known_vector() -> None:
    assert sha256_hex(b"abc") == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


def test_run_ids_are_unique_and_version_4() -> None:
    first, second = new_run_id(), new_run_id()
    assert isinstance(first, UUID)
    assert first.version == 4
    assert first != second
