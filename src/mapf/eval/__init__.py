"""Phase 2 — measuring whether the forecasts are any good.

Nothing here improves a forecast. It exists to tell whether any change to the
pipeline improves one, which is a different and harder job.

Parameterised by Protocols like `pipeline`, and forbidden from importing
`providers` or `data` (ADR 0004), so the whole harness runs against fixtures.
"""
