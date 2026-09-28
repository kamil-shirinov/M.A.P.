"""The local analysis server: one origin, serving the app and one endpoint.

This is the only place in the project where a page can cause a forecast to exist.
Everything else is a read of `runs/` or of an export, which is why the hosted copy
is safe to publish and why the journal cannot compute a score (ADR 0035).

The boundary is kept narrow on purpose. `analyse` turns a ticker into a run by
calling the same primitives `map run --from-edgar` calls — not a second copy of
them — and `server` does nothing but check the request, route it, and stream what
`analyse` yields. See ADR 0036.
"""
