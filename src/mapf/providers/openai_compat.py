"""The only module in this project that speaks HTTP to a model.

No backend vendor is named here, and none may be: the base URL and the model
aliases come from configuration, and this module treats every server as the same
OpenAI-compatible surface (`CLAUDE.md` §3). It also never branches on which server
it believes it is talking to — the fingerprint resolver asks what fields are
present and composes from those, which is what keeps ADR 0001's ladder
vendor-neutral.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import TracebackType
from typing import Any, Self

import httpx
import structlog

from mapf.core.errors import (
    InferenceError,
    InferenceProtocolError,
    InferenceStatusError,
    InferenceTimeoutError,
    InferenceUnreachableError,
    ModelBudgetExhaustedError,
    ModelNotAvailableError,
)
from mapf.core.hashing import canonical_json, sha256_hex
from mapf.core.ports import (
    FingerprintSource,
    LLMResponse,
    ModelInfo,
    RenderedPrompt,
    SamplingParams,
)

_logger = structlog.get_logger(__name__)

# An explicit weight digest, if the response happens to carry one.
_DIGEST_FIELDS = ("digest", "sha256")

# Identifying metadata to fold into a composite fingerprint when no digest is
# exposed. Every one is read with .get() and absence is tolerated (ADR 0001).
# `owned_by` and `object` are excluded on purpose: they are structural, constant
# across models, and would add nothing but noise to the hash.
_COMPOSITE_FIELDS = (
    "created",
    "modified_at",
    "size",
    "context_length",
    "max_model_len",
    "quantization",
    "quantization_level",
    "parameter_size",
    "parameters",
    "family",
    "families",
    "format",
)


def _fingerprint(entry: Mapping[str, Any]) -> tuple[str, FingerprintSource, tuple[str, ...]]:
    """Resolve the strongest available identity for one model (ADR 0001).

    Degrades digest -> composite -> tag. A composite is weaker than a digest — two
    builds of the same weights can collide, and unrelated metadata churn can
    invalidate — but it is strictly better than a bare tag, because a re-pointed
    tag almost always changes at least the size or the creation time.
    """
    model_id = str(entry.get("id", ""))

    for field in _DIGEST_FIELDS:
        value = entry.get(field)
        if isinstance(value, str) and value:
            return value, "digest", (field,)

    present = {field: entry[field] for field in _COMPOSITE_FIELDS if entry.get(field) is not None}
    if present:
        payload = {"id": model_id, "fields": present}
        return (
            sha256_hex(canonical_json(payload).encode("utf-8")),
            "composite",
            tuple(sorted(present)),
        )

    return model_id, "tag", ()


class OpenAICompatProvider:
    """An `LLMProvider` over an OpenAI-compatible HTTP API."""

    def __init__(
        self,
        base_url: str,
        *,
        connect_timeout_s: float,
        read_timeout_s: float,
        client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._read_timeout_s = read_timeout_s
        # Connect and read are separate, and the difference is the whole point
        # (ADR 0008). Connect is short because the server is local: if it will not
        # accept a socket quickly it is not running. Read is long because a cold
        # model load on 16 GB routinely takes tens of seconds before a first token.
        self._timeout = httpx.Timeout(
            connect=connect_timeout_s,
            read=read_timeout_s,
            write=connect_timeout_s,
            pool=connect_timeout_s,
        )
        self._owns_client = client is None
        self._client = client or httpx.Client(base_url=self._base_url, timeout=self._timeout)

    # -- lifecycle ---------------------------------------------------------
    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    # -- transport ---------------------------------------------------------
    def _request(self, method: str, path: str, *, json: Any = None, model_id: str = "") -> Any:
        """Issue one request and translate every failure into a typed error.

        The ordering of the except clauses matters: `ConnectTimeout` is both a
        timeout and a connect failure, and it means "no server", not "slow model".
        """
        try:
            response = self._client.request(method, path, json=json, timeout=self._timeout)
        except (httpx.ConnectTimeout, httpx.ConnectError) as err:
            raise InferenceUnreachableError(self._base_url, type(err).__name__) from err
        except httpx.TimeoutException as err:
            raise InferenceTimeoutError(model_id or path, self._read_timeout_s) from err
        except httpx.TransportError as err:
            raise InferenceUnreachableError(self._base_url, type(err).__name__) from err
        except httpx.HTTPError as err:  # malformed exchange below the JSON layer
            raise InferenceProtocolError(f"HTTP error talking to {self._base_url}: {err}") from err

        if not response.is_success:
            # Every non-2xx leaves here as a status error, 404 included. Translating
            # 404 to "model missing" *here* would be wrong twice: a 404 on /models
            # means the endpoint is absent, not that a model is, and enriching it by
            # calling list_models() re-enters this method and recurses forever.
            # `complete` does that translation, where the model id is known.
            raise InferenceStatusError(response.status_code, response.text)

        try:
            return response.json()
        except ValueError as err:
            raise InferenceProtocolError(
                f"response from {path} was not JSON: {response.text[:300]!r}"
            ) from err

    def _loaded_ids(self) -> tuple[str, ...]:
        """Best-effort model list, used only to enrich a missing-model error.

        Naming what *is* loaded turns a dead end into an actionable message —
        the usual cause is a naming difference between backends. Failing to fetch
        it must not mask the original error, so every inference failure here is
        swallowed and the caller simply gets an empty list.
        """
        try:
            return tuple(info.id for info in self.list_models())
        except InferenceError:
            return ()

    # -- LLMProvider -------------------------------------------------------
    def list_models(self) -> Sequence[ModelInfo]:
        payload = self._request("GET", "/models")
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            raise InferenceProtocolError(
                f"GET /models did not return a 'data' list, got {type(data).__name__}"
            )

        models: list[ModelInfo] = []
        for entry in data:
            if not isinstance(entry, dict) or not entry.get("id"):
                raise InferenceProtocolError(f"malformed entry in GET /models: {entry!r}")
            fingerprint, source, fields = _fingerprint(entry)
            models.append(
                ModelInfo(
                    id=str(entry["id"]),
                    fingerprint=fingerprint,
                    fingerprint_source=source,
                    fingerprint_fields=fields,
                )
            )

        weak = [info.id for info in models if info.fingerprint_source == "tag"]
        if weak:
            _logger.warning(
                "weight_pinning_unavailable",
                models=weak,
                consequence="a re-pointed tag cannot be detected; cache may serve stale weights",
            )
        return tuple(models)

    def complete(
        self,
        *,
        model: ModelInfo,
        prompt: RenderedPrompt,
        sampling: SamplingParams,
        json_schema: Mapping[str, Any] | None = None,
        attempt: int = 0,
    ) -> LLMResponse:
        body: dict[str, Any] = {
            "model": model.id,
            "messages": [
                {"role": message.role, "content": message.content} for message in prompt.messages
            ],
            "temperature": sampling.temperature,
        }
        if sampling.seed is not None:
            body["seed"] = sampling.seed
        if sampling.top_p is not None:
            body["top_p"] = sampling.top_p
        if sampling.max_tokens is not None:
            body["max_tokens"] = sampling.max_tokens
        if sampling.frequency_penalty is not None:
            body["frequency_penalty"] = sampling.frequency_penalty
        if json_schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": prompt.template_name,
                    "strict": True,
                    "schema": dict(json_schema),
                },
            }

        try:
            payload = self._request("POST", "/chat/completions", json=body, model_id=model.id)
        except InferenceStatusError as err:
            if err.status_code == httpx.codes.NOT_FOUND:
                # Only here is the model id known, and only here does a 404 actually
                # mean "that model is not on this server".
                raise ModelNotAvailableError(model.id, self._loaded_ids()) from err
            raise
        return self._parse_completion(payload, model)

    @staticmethod
    def _parse_completion(payload: Any, model: ModelInfo) -> LLMResponse:
        if not isinstance(payload, dict):
            raise InferenceProtocolError(f"completion payload was {type(payload).__name__}")

        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise InferenceProtocolError("completion response contained no choices")

        first = choices[0]
        message = first.get("message") if isinstance(first, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise InferenceProtocolError(
                f"completion choice had no string content, got {type(content).__name__}"
            )

        usage = payload.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        details = usage.get("completion_tokens_details")
        details = details if isinstance(details, dict) else {}
        reasoning_tokens = details.get("reasoning_tokens")

        reasoning_text = _reasoning_text(message)
        finish_reason = first.get("finish_reason")
        if not content.strip() and finish_reason == "length":
            # A reasoning-capable build streams into `reasoning_content` and only
            # then writes its answer. Out of budget first, `content` is empty while
            # thousands of tokens were generated — which looks exactly like a
            # refusal and is not one.
            raise ModelBudgetExhaustedError(
                str(payload.get("model") or model.id),
                int(usage.get("completion_tokens") or 0),
                int(reasoning_tokens or 0),
                reasoning_text,
            )

        return LLMResponse(
            text=content,
            # The server's own id, not the alias we asked for: they can differ, and
            # the manifest should record what actually answered.
            model_id=str(payload.get("model") or model.id),
            finish_reason=finish_reason,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            reasoning_tokens=reasoning_tokens,
            reasoning_text=reasoning_text or None,
            cache_hit=False,
        )


def _reasoning_text(message: object) -> str:
    """The model's reasoning, under whichever key this backend uses for it.

    Not vendor coupling in the sense `CLAUDE.md` §3 forbids: nothing branches on
    which key matched, and an unrecognised one costs a missing diagnostic rather
    than a wrong answer. The alternative — recording only the token COUNT, which is
    what happened before — makes a runaway countable and unreadable.
    """
    if not isinstance(message, dict):
        return ""
    for key in ("reasoning_content", "reasoning"):
        value = message.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""
