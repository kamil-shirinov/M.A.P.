"""The SEC User-Agent policy, at the boundary that sends the header.

EDGAR answers a request without a descriptive User-Agent with 403 and blocks the IP
for about ten minutes, so a placeholder must be refused before any request goes out.
That was never in doubt; *where* it was refused was wrong. It lived on the settings
model, so loading configuration at all refused while the shipped `config/default.toml`
carried its placeholder — which made `map export`, a command that reads local files
and contacts nobody, fail on a credential it never uses, and made 45 tests pass only
on a machine with a gitignored `config/local.toml`.

These pin the policy where it now lives, and pin that it cannot quietly move again.
"""

from __future__ import annotations

import re
from pathlib import Path

import httpx
import pytest

from mapf.core.errors import ConfigurationError, PlaceholderConfigError
from mapf.data.exhibits import EdgarExhibits
from mapf.data.filings import EdgarFilings
from mapf.data.sec import PLACEHOLDER_MARKER, require_usable_user_agent
from mapf.data.symbols import Throttle, fetch_sec_tickers

GOOD = "Jane Doe jane@example.com M.A.P. research tool"
PLACEHOLDER = "REPLACE_ME <your.name> <your.email@example.com> M.A.P. research tool"

SRC = Path(__file__).parents[2] / "src" / "mapf"


def _client() -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))


# ---------------------------------------------------------------------------
# The policy
# ---------------------------------------------------------------------------
def test_a_usable_agent_passes_through_unchanged() -> None:
    """It returns the value so a caller assigns THROUGH it, which makes the check
    impossible to perform and then ignore."""
    assert require_usable_user_agent(GOOD) == GOOD


def test_the_placeholder_is_refused_with_the_remedy_in_the_message() -> None:
    """A config error without a remedy just tells the operator they are wrong."""
    with pytest.raises(PlaceholderConfigError) as caught:
        require_usable_user_agent(PLACEHOLDER)

    message = str(caught.value)
    assert caught.value.key == "data.sec.user_agent"
    assert "MAP_DATA__SEC__USER_AGENT" in message
    assert "403" in message


def test_a_name_with_no_contact_address_is_refused() -> None:
    """A name with no email is what actually earns the block."""
    with pytest.raises(ConfigurationError, match="no contact address"):
        require_usable_user_agent("M.A.P. research tool 1.0")


def test_surrounding_whitespace_does_not_smuggle_a_placeholder_through() -> None:
    with pytest.raises(PlaceholderConfigError):
        require_usable_user_agent(f"   {PLACEHOLDER}   ")


# ---------------------------------------------------------------------------
# Every adapter that sends the header
# ---------------------------------------------------------------------------
def test_the_filings_adapter_refuses_before_it_is_usable() -> None:
    """At construction, not at fetch: `map corpus run` and `map evaluate` build
    these up front, so the original fail-before-any-request property survives."""
    with pytest.raises(PlaceholderConfigError):
        EdgarFilings(
            object(),  # type: ignore[arg-type]
            user_agent=PLACEHOLDER,
            client=_client(),
            throttle=Throttle(1000.0, sleep=lambda _: None),
        )


def test_the_exhibits_adapter_refuses_before_it_is_usable() -> None:
    with pytest.raises(PlaceholderConfigError):
        EdgarExhibits(
            user_agent=PLACEHOLDER,
            client=_client(),
            throttle=Throttle(1000.0, sleep=lambda _: None),
        )


def test_the_ticker_fetch_refuses_before_the_request() -> None:
    """A function, not a class, so it validates on the way in rather than in a
    constructor. Same guarantee: nothing reaches the wire."""
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={})

    with pytest.raises(PlaceholderConfigError):
        fetch_sec_tickers(
            "https://example.test/tickers.json",
            user_agent=PLACEHOLDER,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            throttle=Throttle(1000.0, sleep=lambda _: None),
        )

    assert sent == []


# ---------------------------------------------------------------------------
# It cannot quietly move again
# ---------------------------------------------------------------------------
def test_every_sec_header_goes_through_the_guard() -> None:
    """A fourth caller added without a check is the way this regresses.

    Any module that puts a `User-Agent` on a request must also name the validator.
    Structural rather than remembered, because the failure mode is a header that
    works on the author's machine and 403s everywhere else.
    """
    senders = [
        path
        for path in SRC.rglob("*.py")
        if re.search(r'headers=\{[^}]*"User-Agent"', path.read_text(encoding="utf-8"))
    ]

    assert senders, "no module sends a User-Agent; this test has lost its subject"
    for path in senders:
        body = path.read_text(encoding="utf-8")
        assert "require_usable_user_agent" in body, f"{path.name} sends a header unguarded"


def test_settings_no_longer_enforces_the_policy() -> None:
    """The regression that matters is someone re-adding it there for convenience,
    which would silently re-couple the offline suite to operator config."""
    loader = (SRC / "settings" / "loader.py").read_text(encoding="utf-8")

    assert PLACEHOLDER_MARKER not in loader
    assert "require_usable_user_agent" not in loader
