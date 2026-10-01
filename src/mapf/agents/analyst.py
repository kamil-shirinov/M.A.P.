"""Agent 2 — three-scenario reasoning, in prose."""

from __future__ import annotations

from datetime import date

from pydantic import Field

from mapf.agents.base import LLMAgent
from mapf.core.errors import AnalystInputError, AnalystOutputError
from mapf.core.models import (
    DomainModel,
    MaterialFacts,
    ScenarioNarrative,
    Ticker,
    TrustedText,
    UntrustedText,
)
from mapf.core.quarantine import quarantine

# Prose cannot be schema-checked, and inventing elaborate validation for it would
# manufacture confidence without evidence. These two bounds catch the failures that
# are unambiguous — a refusal, an empty response, a truncation, a runaway loop —
# and nothing else. The trace is the real record, and a human reading it is the
# real check.
MIN_LENGTH = 100
MAX_LENGTH = 20_000

# Experiment A2 (ADR 0042): the frozen template plus one trusted figure. A separate
# template NAME so `scenario_analyst.v3` keeps the hash the freeze recorded.
REALISED_VOL_TEMPLATE = "scenario_analyst_vol"


class AnalystRequest(DomainModel):
    ticker: Ticker
    as_of_date: date
    horizon_days: int = Field(ge=1, le=252)
    facts: MaterialFacts
    # Annualised, a decimal fraction, from the run's own settled closes (A2). `None`
    # for the frozen system, which is shown nothing of the kind. Bounded so a nan or
    # a percentage cannot reach a prompt.
    realised_vol: float | None = Field(default=None, gt=0.0, le=10.0)


class AnalystAgent(LLMAgent):
    """`AnalystRequest -> ScenarioNarrative`."""

    TEMPLATE = "scenario_analyst"

    @property
    def takes_realised_vol(self) -> bool:
        """Does this agent's template ask for a realised volatility (A2)?

        Derived from the template rather than held as a second flag, so the two
        cannot disagree about which prompt is in use.
        """
        return self._template == REALISED_VOL_TEMPLATE

    def run(self, request: AnalystRequest, /) -> ScenarioNarrative:
        trusted = {
            "ticker": TrustedText(request.ticker),
            "as_of_date": TrustedText(request.as_of_date.isoformat()),
            "horizon_days": TrustedText(str(request.horizon_days)),
        }
        # Both mismatches are refused, because both run quietly as the wrong arm: a
        # figure handed to a template that has no slot for it would be dropped and
        # the run counted as having seen it, and a template that needs one and has
        # none cannot be rendered as anything but the control.
        if self.takes_realised_vol:
            if request.realised_vol is None:
                raise AnalystInputError(
                    f"{self._template} needs a realised volatility and the request has none"
                )
            trusted["realised_vol"] = TrustedText(f"{request.realised_vol:.2f}")
        elif request.realised_vol is not None:
            raise AnalystInputError(
                f"{self._template} has no slot for a realised volatility, and the request "
                "carries one; it would be dropped and the run counted as having seen it"
            )
        prompt = self._render(
            self._template,
            self._version,
            trusted=trusted,
            untrusted={"material_facts": quarantine("\n".join(request.facts.facts))},
        )
        narrative = self._complete(prompt).text.strip()

        if len(narrative) < MIN_LENGTH:
            raise AnalystOutputError(
                "too short to be three reasoned scenarios; likely a refusal or a "
                "truncated response",
                len(narrative),
            )
        if len(narrative) > MAX_LENGTH:
            raise AnalystOutputError("implausibly long; likely a generation loop", len(narrative))

        return ScenarioNarrative(
            ticker=request.ticker,
            horizon_days=request.horizon_days,
            text=UntrustedText(narrative),
            source_doc_ids=request.facts.source_doc_ids,
        )
