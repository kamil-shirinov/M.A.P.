"""Does this backend accept the decode schema?

Open question 8 is the most likely first-run failure, and without this it would
surface at the *end* of a three-minute pipeline after two model swaps — the worst
possible place to learn that a grammar engine cannot resolve `$ref`.

`Scenario` appears three times in `ScenarioSet`, so pydantic emits `$defs` plus
three `$ref`s rather than inlining. Most constrained-decoding implementations
resolve that; some do not. The probe sends one minimal request against the **real**
`decode_schema(ScenarioSet)` and reports which.

Three outcomes rather than two, because "the request succeeded" is not the same as
"the grammar was enforced": a backend that silently ignores `response_format`
returns 200 and prose, and would look identical to a working one until Agent 3
started failing validation on every attempt.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from mapf.core.errors import (
    InferenceError,
    InferenceStatusError,
    InferenceTimeoutError,
    InferenceUnreachableError,
)
from mapf.core.models import Scenario, ScenarioSet
from mapf.core.ports import LLMProvider, ModelInfo, PromptStore, SamplingParams
from mapf.core.schema import decode_schema

TEMPLATE = "grammar_probe"
VERSION = "v1"

BRANCHES = frozenset({"bullish", "base_case", "bearish"})
# Read from the model rather than restated, so a field added to `Scenario` cannot
# leave the probe checking a shape the pipeline no longer uses.
FIELDS = frozenset(Scenario.model_fields)

Outcome = Literal["enforced", "accepted_not_enforced", "rejected", "inconclusive"]

_FLATTEN_REMEDY = (
    "Flatten the schema: inline the Scenario definition into each of the three "
    "branches so no $defs/$ref remains. That is a change to "
    "mapf.core.schema.decode_schema, and it closes open question 8 in notebook/STATE.md."
)


@dataclass(frozen=True)
class GrammarProbe:
    outcome: Outcome
    detail: str
    remedy: str | None = None

    @property
    def ok(self) -> bool:
        return self.outcome == "enforced"


def probe_grammar(
    *,
    provider: LLMProvider,
    prompts: PromptStore,
    model: ModelInfo,
    sampling: SamplingParams,
) -> GrammarProbe:
    """One constrained request against the real schema.

    `provider` must be **uncached**. A cached probe replays its own earlier answer
    and reports on a server it never contacted, which is worse than not probing.
    """
    schema = decode_schema(ScenarioSet)
    prompt = prompts.render(TEMPLATE, VERSION)

    try:
        response = provider.complete(
            model=model, prompt=prompt, sampling=sampling, json_schema=schema
        )
    except InferenceStatusError as err:
        return GrammarProbe(
            outcome="rejected",
            detail=f"the backend rejected the request carrying the schema ({err}).",
            remedy=_FLATTEN_REMEDY,
        )
    except InferenceTimeoutError as err:
        return GrammarProbe(
            outcome="inconclusive",
            detail=f"timed out ({err}). On this hardware that is usually a cold model load.",
            remedy="Run `map health` again once the model is resident.",
        )
    except (InferenceUnreachableError, InferenceError) as err:
        return GrammarProbe(outcome="inconclusive", detail=str(err))

    try:
        payload = json.loads(response.text)
    except ValueError:
        return GrammarProbe(
            outcome="accepted_not_enforced",
            detail=(
                "the request succeeded but the reply was not JSON, so the backend "
                "accepted response_format and then ignored it."
            ),
            remedy=(
                "Agent 3 will rely on the repair loop for every call and may exhaust "
                "it. Check that your backend supports json_schema response_format, "
                "not merely json_object."
            ),
        )

    if not isinstance(payload, dict):
        return GrammarProbe(
            outcome="accepted_not_enforced",
            detail="the reply was JSON but not an object, so the grammar was not applied.",
            remedy="As above: confirm json_schema response_format is supported.",
        )

    # EXACT keys, not a superset. `additionalProperties: false` means an enforced
    # grammar emits these three and nothing else — so an extra key is evidence
    # AGAINST enforcement, and the previous `>=` scored it as enforcement (ADR
    # 0022). The same reasoning one level down: each branch carries exactly the
    # four fields the model declares.
    if set(payload) != BRANCHES:
        extra = sorted(set(payload) - BRANCHES)
        return GrammarProbe(
            outcome="accepted_not_enforced",
            detail=(
                f"the reply carried unexpected key(s) {extra}, which "
                "additionalProperties:false makes unreachable under an enforced grammar."
                if extra
                else "the reply was missing required branches, so the grammar was not applied."
            ),
            remedy="As above: confirm json_schema response_format is supported.",
        )

    for branch in sorted(BRANCHES):
        body = payload[branch]
        if not isinstance(body, dict) or set(body) != FIELDS:
            return GrammarProbe(
                outcome="accepted_not_enforced",
                detail=(
                    f"branch {branch!r} did not carry exactly the declared fields, so "
                    "the grammar was shaping the top level only."
                ),
                remedy="As above: confirm json_schema response_format is supported.",
            )

    # Deliberately not validating bounds or cross-field invariants. The probe asks
    # whether the grammar held its SHAPE, not whether a placeholder answer is a good
    # forecast — those are exactly the failures the repair loop exists for (ADR 0002).
    return GrammarProbe(
        outcome="enforced",
        detail="the backend accepted $defs/$ref and constrained the output to the schema.",
    )
