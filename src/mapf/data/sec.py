"""The SEC User-Agent policy, enforced where the header is actually sent.

EDGAR answers a request without a descriptive User-Agent with 403 and blocks the IP
for about ten minutes, so a placeholder must be refused before any request goes out.
That much was never in doubt. **Where** it was refused was wrong.

The check lived on the settings model, so *loading configuration at all* refused
while the shipped `config/default.toml` carried its placeholder. Every command
inherited a network-safety guard, including the ones that make no network calls:
`map export` reads local files and failed on it, and so did 45 tests, which pass on
a machine with a gitignored `config/local.toml` and fail on every fresh clone. A
suite whose central claim is that it runs offline was refusing to run for want of a
credential it never uses.

So the policy moves to the boundary it is about. Exactly three call sites put this
header on the wire — `EdgarFilings`, `EdgarExhibits` and `fetch_sec_tickers` — and
each validates as it is constructed. The original benefit survives intact: those
adapters are built up front by the commands that need them, so `map corpus run` and
`map symbols sync` still refuse before a single request, with the same message.

`test_every_sec_header_goes_through_the_guard` keeps a fourth caller from being
added without one.
"""

from __future__ import annotations

from mapf.core.errors import ConfigurationError, PlaceholderConfigError

PLACEHOLDER_MARKER = "REPLACE_ME"

SEC_USER_AGENT_HINT = (
    "SEC EDGAR returns 403 and blocks the IP for about ten minutes without a "
    "descriptive User-Agent carrying a name and a contact email address. Set "
    "MAP_DATA__SEC__USER_AGENT, or edit data.sec.user_agent in config/default.toml, "
    "to something of the form 'Jane Doe jane@example.com M.A.P. research tool'."
)


def require_usable_user_agent(agent: str) -> str:
    """The agent, or a typed refusal naming the remedy.

    Returns the value so a caller can assign through it — `self._user_agent =
    require_usable_user_agent(user_agent)` — which makes the check impossible to
    perform and then ignore.

    `PlaceholderConfigError` rather than a `ValidationError`: this is a policy
    failure with one specific remedy, and the remedy should be the whole message
    rather than one line inside a blob.
    """
    stripped = agent.strip()
    if PLACEHOLDER_MARKER in stripped:
        raise PlaceholderConfigError("data.sec.user_agent", agent, SEC_USER_AGENT_HINT)
    if "@" not in stripped:
        raise ConfigurationError(
            f"config key 'data.sec.user_agent' has no contact address: {agent!r}. "
            + SEC_USER_AGENT_HINT
        )
    return agent
