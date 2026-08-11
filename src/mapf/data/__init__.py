"""Market data, symbols, and news — everything that reaches a third party.

Three separate concerns, one shared property: none of them may be reached from
`agents` or `pipeline` (ADR 0004), and all of them are injectable so the default
test run touches no network.

`news.py` is where `UntrustedText` is constructed for real. Everything above this
layer treats that text as tainted and cannot un-taint it (ADR 0005).
"""
