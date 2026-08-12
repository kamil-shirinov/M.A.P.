"""The HTTP adapter, driven entirely through `httpx.MockTransport`.

No network, no server, no sleeping. Every failure mode the caller must be able to
tell apart has its own test, because the whole argument of ADR 0008 is that these
are different situations with different remedies — and a taxonomy that is never
exercised is a taxonomy that quietly collapses.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
from structlog.testing import capture_logs

from mapf.core.errors import (
    InferenceProtocolError,
    InferenceStatusError,
    InferenceTimeoutError,
    InferenceUnreachableError,
    ModelNotAvailableError,
)
from mapf.core.ports import Message, ModelInfo, RenderedPrompt, SamplingParams
from mapf.providers.openai_compat import OpenAICompatProvider

BASE_URL = "http://localhost:1234/v1"

PROMPT = RenderedPrompt(
    template_name="structuralist",
    template_version="v1",
    template_sha256="0" * 64,
    messages=(Message(role="user", content="produce scenarios"),),
)
SAMPLING = SamplingParams(temperature=0.0, seed=7)
MODEL = ModelInfo(id="qwen3-4b", fingerprint="fp", fingerprint_source="tag")

COMPLETION = {
    "model": "qwen3-4b",
    "choices": [
        {"message": {"role": "assistant", "content": '{"ok": true}'}, "finish_reason": "stop"}
    ],
    "usage": {"prompt_tokens": 120, "completion_tokens": 44},
}


def _provider(handler: Callable[[httpx.Request], httpx.Response]) -> OpenAICompatProvider:
    client = httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(handler))
    return OpenAICompatProvider(
        BASE_URL, connect_timeout_s=10.0, read_timeout_s=600.0, client=client
    )


def _responds(payload: object, status: int = 200) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)

    return handler


def _raises(error: Exception) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    return handler


# ---------------------------------------------------------------------------
# Discovery and fingerprinting (ADR 0001)
# ---------------------------------------------------------------------------
def test_a_digest_is_used_when_the_server_exposes_one() -> None:
    provider = _provider(_responds({"data": [{"id": "qwen3-4b", "digest": "sha256-abc"}]}))
    (info,) = provider.list_models()
    assert (info.fingerprint, info.fingerprint_source) == ("sha256-abc", "digest")
    assert info.fingerprint_fields == ("digest",)


def test_a_composite_is_built_from_whatever_fields_are_present() -> None:
    """No field is required and every one is read defensively — which is what keeps
    this vendor-neutral rather than a guess about which server is answering."""
    provider = _provider(
        _responds({"data": [{"id": "gemma", "created": 1_754_700_000, "size": 7_600_000_000}]})
    )
    (info,) = provider.list_models()
    assert info.fingerprint_source == "composite"
    assert info.fingerprint_fields == ("created", "size")
    assert len(info.fingerprint) == 64


def test_a_composite_changes_when_the_metadata_changes() -> None:
    """The point of the composite: a re-pointed tag almost always moves the size
    or the creation time, even when the id is identical."""
    first = _provider(_responds({"data": [{"id": "g", "size": 1}]})).list_models()[0]
    second = _provider(_responds({"data": [{"id": "g", "size": 2}]})).list_models()[0]
    assert first.fingerprint != second.fingerprint


def test_a_composite_ignores_field_ordering() -> None:
    a = _provider(_responds({"data": [{"id": "g", "size": 1, "created": 9}]})).list_models()[0]
    b = _provider(_responds({"data": [{"id": "g", "created": 9, "size": 1}]})).list_models()[0]
    assert a.fingerprint == b.fingerprint


def test_a_bare_id_degrades_to_the_tag() -> None:
    provider = _provider(_responds({"data": [{"id": "qwen3-4b", "object": "model"}]}))
    (info,) = provider.list_models()
    assert (info.fingerprint, info.fingerprint_source) == ("qwen3-4b", "tag")
    assert info.fingerprint_fields == ()


def test_tag_only_pinning_warns_rather_than_failing_silently() -> None:
    """The limitation is stated, never hidden (ADR 0001)."""
    provider = _provider(_responds({"data": [{"id": "qwen3-4b"}]}))
    with capture_logs() as logs:
        provider.list_models()
    warnings = [entry for entry in logs if entry["event"] == "weight_pinning_unavailable"]
    assert warnings and warnings[0]["models"] == ["qwen3-4b"]


def test_models_without_a_data_list_is_a_protocol_error() -> None:
    with pytest.raises(InferenceProtocolError, match="data"):
        _provider(_responds({"models": []})).list_models()


def test_a_model_entry_without_an_id_is_a_protocol_error() -> None:
    with pytest.raises(InferenceProtocolError, match="malformed entry"):
        _provider(_responds({"data": [{"object": "model"}]})).list_models()


# ---------------------------------------------------------------------------
# Completion
# ---------------------------------------------------------------------------
def test_completion_parses_content_usage_and_finish_reason() -> None:
    provider = _provider(_responds(COMPLETION))
    response = provider.complete(model=MODEL, prompt=PROMPT, sampling=SAMPLING)
    assert response.text == '{"ok": true}'
    assert response.finish_reason == "stop"
    assert (response.prompt_tokens, response.completion_tokens) == (120, 44)
    assert response.cache_hit is False


def test_completion_reports_the_id_the_server_actually_used() -> None:
    """The alias we asked for and the id that answered can differ; the manifest
    should record what answered."""
    provider = _provider(_responds({**COMPLETION, "model": "qwen3-4b-instruct-q4"}))
    assert provider.complete(model=MODEL, prompt=PROMPT, sampling=SAMPLING).model_id == (
        "qwen3-4b-instruct-q4"
    )


def test_sampling_parameters_are_sent_and_absent_ones_omitted() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=COMPLETION)

    _provider(handler).complete(model=MODEL, prompt=PROMPT, sampling=SAMPLING)
    assert seen["temperature"] == 0.0
    assert seen["seed"] == 7
    # top_p and max_tokens were None and must not be sent as nulls.
    assert "top_p" not in seen
    assert "max_tokens" not in seen


def test_optional_sampling_parameters_are_sent_when_set() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=COMPLETION)

    _provider(handler).complete(
        model=MODEL,
        prompt=PROMPT,
        sampling=SamplingParams(temperature=0.7, top_p=0.9, max_tokens=512),
    )
    assert seen["top_p"] == 0.9
    assert seen["max_tokens"] == 512


def test_a_json_schema_is_wired_into_response_format() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=COMPLETION)

    schema = {"type": "object", "properties": {}, "additionalProperties": False}
    _provider(handler).complete(model=MODEL, prompt=PROMPT, sampling=SAMPLING, json_schema=schema)
    response_format = seen["response_format"]
    assert isinstance(response_format, dict)
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    assert response_format["json_schema"]["schema"] == schema


def test_no_response_format_when_no_schema_is_given() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=COMPLETION)

    _provider(handler).complete(model=MODEL, prompt=PROMPT, sampling=SAMPLING)
    assert "response_format" not in seen


# ---------------------------------------------------------------------------
# Failure taxonomy (ADR 0008) — these must never collapse into one another
# ---------------------------------------------------------------------------
def test_connection_refused_means_the_server_is_down() -> None:
    with pytest.raises(InferenceUnreachableError, match="Start the backend") as caught:
        _provider(_raises(httpx.ConnectError("refused"))).complete(
            model=MODEL, prompt=PROMPT, sampling=SAMPLING
        )
    assert caught.value.base_url == BASE_URL


def test_a_connect_timeout_is_a_dead_server_not_a_loading_model() -> None:
    """ConnectTimeout is both a timeout and a connect failure. It means no server."""
    with pytest.raises(InferenceUnreachableError):
        _provider(_raises(httpx.ConnectTimeout("no route"))).complete(
            model=MODEL, prompt=PROMPT, sampling=SAMPLING
        )


def test_a_read_timeout_points_at_a_cold_model_load() -> None:
    with pytest.raises(InferenceTimeoutError, match="cold model load") as caught:
        _provider(_raises(httpx.ReadTimeout("slow"))).complete(
            model=MODEL, prompt=PROMPT, sampling=SAMPLING
        )
    assert caught.value.model_id == "qwen3-4b"
    assert caught.value.read_timeout_s == 600.0


def test_loading_and_down_are_different_types() -> None:
    """The requirement stated plainly: these must never surface as the same error."""
    assert not issubclass(InferenceTimeoutError, InferenceUnreachableError)
    assert not issubclass(InferenceUnreachableError, InferenceTimeoutError)


def test_a_404_means_the_model_is_not_present() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "llama-3.2-3b"}]})
        return httpx.Response(404, json={"error": "model not found"})

    with pytest.raises(ModelNotAvailableError) as caught:
        _provider(handler).complete(model=MODEL, prompt=PROMPT, sampling=SAMPLING)
    assert caught.value.alias == "qwen3-4b"
    # The 404 path re-queries discovery so the message names what IS loaded.
    assert "llama-3.2-3b" in str(caught.value)


def test_a_404_still_reports_when_discovery_also_fails() -> None:
    """Enriching the message must never mask the original error."""
    with pytest.raises(ModelNotAvailableError, match=r"\(none\)"):
        _provider(_responds({"error": "nope"}, status=404)).complete(
            model=MODEL, prompt=PROMPT, sampling=SAMPLING
        )


def test_a_500_is_a_status_error_carrying_the_body() -> None:
    with pytest.raises(InferenceStatusError) as caught:
        _provider(_responds({"error": "out of memory"}, status=500)).complete(
            model=MODEL, prompt=PROMPT, sampling=SAMPLING
        )
    assert caught.value.status_code == 500
    assert "out of memory" in caught.value.body


def test_a_non_json_body_is_a_protocol_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>proxy error</html>")

    with pytest.raises(InferenceProtocolError, match="not JSON"):
        _provider(handler).complete(model=MODEL, prompt=PROMPT, sampling=SAMPLING)


@pytest.mark.parametrize(
    "payload",
    [
        {"choices": []},
        {"choices": [{"message": {}}]},
        {"choices": [{"message": {"content": None}}]},
        {"choices": "not-a-list"},
        [],
    ],
    ids=["empty", "no-content", "null-content", "not-a-list", "not-an-object"],
)
def test_malformed_completions_are_protocol_errors(payload: object) -> None:
    with pytest.raises(InferenceProtocolError):
        _provider(_responds(payload)).complete(model=MODEL, prompt=PROMPT, sampling=SAMPLING)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
def test_a_generic_transport_error_reads_as_unreachable() -> None:
    """Network-level failures below HTTP are the server not being there."""
    with pytest.raises(InferenceUnreachableError):
        _provider(_raises(httpx.NetworkError("reset"))).list_models()


def test_a_protocol_violation_below_json_is_a_protocol_error() -> None:
    with pytest.raises(InferenceProtocolError, match="HTTP error"):
        _provider(_raises(httpx.TooManyRedirects("loop"))).list_models()


def test_a_404_on_models_is_a_status_error_not_a_missing_model() -> None:
    """A 404 on discovery means the endpoint is absent, not that a model is —
    and translating it there would recurse through the enrichment path."""
    with pytest.raises(InferenceStatusError) as caught:
        _provider(_responds({"error": "no such route"}, status=404)).list_models()
    assert caught.value.status_code == 404


def test_a_client_we_created_is_closed_by_us() -> None:
    provider = OpenAICompatProvider(BASE_URL, connect_timeout_s=1.0, read_timeout_s=2.0)
    with provider:
        pass
    assert provider._client.is_closed is True  # noqa: SLF001


def test_an_injected_client_is_not_closed_by_us() -> None:
    """The caller owns what the caller constructed."""
    client = httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(_responds(COMPLETION)))
    with OpenAICompatProvider(BASE_URL, connect_timeout_s=1.0, read_timeout_s=2.0, client=client):
        pass
    assert client.is_closed is False
    client.close()


# ---------------------------------------------------------------------------
# Budget exhaustion — a reasoning model that never reaches its answer
# ---------------------------------------------------------------------------
def test_an_empty_answer_after_a_full_budget_is_not_a_refusal() -> None:
    """The first v2 live run: 6996 completion tokens, empty content, and an error
    saying "likely a refusal". The remedy for a refusal is the prompt's content;
    the remedy here is its length. The message has to distinguish them."""
    from mapf.core.errors import ModelBudgetExhaustedError

    provider = _provider(
        _responds(
            {
                "model": "gemma",
                "choices": [
                    {
                        "message": {"content": "", "reasoning_content": "..."},
                        "finish_reason": "length",
                    }
                ],
                "usage": {
                    "completion_tokens": 6996,
                    "completion_tokens_details": {"reasoning_tokens": 6990},
                },
            }
        )
    )
    with pytest.raises(ModelBudgetExhaustedError) as caught:
        provider.complete(model=MODEL, prompt=PROMPT, sampling=SAMPLING)
    assert caught.value.reasoning_tokens == 6990
    assert "finished thinking" in str(caught.value)
    assert "max_tokens" in str(caught.value)


def test_an_empty_answer_that_stopped_normally_is_not_budget_exhaustion() -> None:
    """`finish_reason=stop` with empty content is a genuine empty answer, and the
    agents' own length checks should judge it."""
    provider = _provider(
        _responds(
            {"model": "m", "choices": [{"message": {"content": ""}, "finish_reason": "stop"}]}
        )
    )
    assert provider.complete(model=MODEL, prompt=PROMPT, sampling=SAMPLING).text == ""


def test_reasoning_tokens_are_recorded_when_the_model_answers() -> None:
    """Invisible unless recorded — and it is the number that explains why a run
    that looks idle is actually working hard."""
    provider = _provider(
        _responds(
            {
                "model": "m",
                "choices": [{"message": {"content": "an answer"}, "finish_reason": "stop"}],
                "usage": {
                    "completion_tokens": 500,
                    "completion_tokens_details": {"reasoning_tokens": 430},
                },
            }
        )
    )
    assert provider.complete(model=MODEL, prompt=PROMPT, sampling=SAMPLING).reasoning_tokens == 430
